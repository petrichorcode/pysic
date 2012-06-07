#! /usr/bin/env python
"""The main module of Pysic.
    
This module defines the user interface in Pysic for setting up potentials
and calculators.
"""

from pysic.core import *
from pysic.utility.error import *
from pysic.interactions.local import Potential
from pysic.interactions.bondorder import Coordinator, BondOrderParameters
from pysic.interactions.coulomb import CoulombSummation
from pysic.charges.relaxation import ChargeRelaxation

import pysic.pysic_fortran as pf
import ase.calculators.neighborlist as nbl
import pysic.utility.f2py as pu

import numpy as np
import ase.calculators.neighborlist as nbl
from itertools import permutations
import copy
import math



neighbor_marginal = 0.5
"""Default skin width for the neighbor list"""

class FastNeighborList(nbl.NeighborList):
    """ASE has a neighbor list class built in, but its implementation is
        currently inefficient, and building of the list is an :math:`O(n^2)`
        operation. This neighbor list class overrides the 
        :meth:`~pysic_utility.FastNeighborList.build` method with
        an :math:`O(n)` time routine. The fast routine is based on a
        spatial partitioning algorithm.
        
        The way cutoffs are handled is also somewhat different to the original
        ASE list. In ASE, the distances for two atoms are compared against
        the sum of the individual cutoffs + neighbor list skin. This list, however,
        searches for the neighbors of each atom at a distance of the cutoff of the
        given atom only, plus skin.
        """
    
    def __init__(self, cutoffs, skin=neighbor_marginal):
        nbl.NeighborList.__init__(self, 
                              cutoffs=cutoffs, 
                              skin=skin, 
                              sorted=False, 
                              self_interaction=False,
                              bothways=True)    
    
    def build(self,atoms):
        """Builds the neighbor list.
            
            The routine requires that the given atomic structure matches
            the one in the core. This is because the method invokes the
            Fortran core to do the neighbor search.
            The method overrides the similar
            method in the original ASE neighborlist class, which directly operates
            on the given structure, so this method also takes the atomic structure 
            as an argument. However, in order to keep the core modification routines in
            the :class:`~pysic.Pysic` class, this method does not change the core
            structure. It does raise an error if the structures do not match, though.
            
            The neighbor search is done via the :meth:`generate_neighbor_lists` routine.
            The routine builds the neighbor list in the core, after which the list is
            fed back to the :class:`~pysic.FastNeighborList` object by looping over all
            atoms and saving the lists of neighbors and offsets.

            Parameters:
            
            atoms: ASE Atoms object
                the structure for which the neighbors are searched
            """
        
        if not Pysic.core.atoms_ready(atoms):
            raise MissingAtomsError("Neighbor list building: Atoms in the core do not match.")
        if Pysic.core.get_atoms() != atoms:
            raise MissingAtomsError("Neighbor list building: Atoms in the core do not match.")
        
        self.positions = atoms.get_positions()
        self.pbc = atoms.get_pbc()
        self.cell = atoms.get_cell()
        
        pf.pysic_interface.generate_neighbor_lists(self.cutoffs)
                
        self.neighbors = [np.empty(0, int) for a in range(len(atoms))]
        self.displacements = [np.empty((0, 3), int) for a in range(len(atoms))]
        
        for i in range(len(atoms)):
            n_nbs = pf.pysic_interface.get_number_of_neighbors_of_atom(i)
            if n_nbs > 0:
                (self.neighbors[i], self.displacements[i]) = pf.pysic_interface.get_neighbor_list_of_atom(i,n_nbs)
                # the offsets are in Fortran array format, so they need to be transposed
                self.displacements[i] = np.transpose(self.displacements[i])
    
        self.nupdates += 1
        



class Pysic:
    """A calculator class providing the necessary methods for interfacing with `ASE`_.

    Pysic is a calculator for evaluating energies and forces for given atomic structures
    according to the given :class:`~pysic.Potential` set. Neither the geometry nor the
    potentials have to be specified upon creating the calculator, as they can be specified
    or changed later. They are necessary for actual calculation, of course.

    Simulation geometries must be defined as `ASE Atoms`_. This object contains both the
    atomistic coordinates and supercell parameters.

    Potentials must be defined as a list of :class:`~pysic.Potential` objects. 
    The total potential of the system is then the sum of the individual potentials.
    
    .. _ASE: https://wiki.fysik.dtu.dk/ase/
    .. _ASE Atoms: https://wiki.fysik.dtu.dk/ase/ase/atoms.html

    Parameters:

    atoms: `ASE Atoms`_ object
        an Atoms object containing the full simulation geometry
    potentials: list of :class:`~pysic.Potential` objects
        list of potentials for describing interactions
    force_initialization: boolean
        If true, calculations always fully initialize the Fortran core.
        If false, the Pysic tries to evaluate what needs updating by
        consulting the :data:`~pysic.Pysic.core` instance of :class:`~pysic.CoreMirror`.
    """

    core = CoreMirror()
    """An object storing the data passed to the core.

    Whenever a :class:`~pysic.Pysic` calculator alters the Fortran core,
    it should also modify the :data:`~pysic.Pysic.core` object so that
    it is always a valid representation of the actual core.
    Then, whenever :class:`~pysic.Pysic` needs to check if the
    representation in the core is up to date, it only needs to compare
    against :data:`~pysic.Pysic.core` instead of accessing the
    Fortran core itself.
    """
    def __init__(self,atoms=None,potentials=None,charge_relaxation=None,
                 coulomb=None,full_initialization=False):
        
        self.neighbor_lists_ready = False
        self.saved_cutoffs = None
        
        self.structure = None
        self.neighbor_list = None
        self.potentials = None
        self.charge_relaxation = None
        self.coulomb = None
        
        self.set_atoms(atoms)
        self.set_potentials(potentials)
        self.set_charge_relaxation(charge_relaxation)
        self.set_coulomb_summation(coulomb)
        
        self.forces = None
        self.stress = None
        self.energy = None
        self.electronegativities = None

        self.force_core_initialization = full_initialization


    def __eq__(self,other):
        try:
            if self.structure != other.structure:
                return False
            if any(self.structure.get_charges() != other.structure.get_charges()):
                return False
            if self.neighbor_list != other.neighbor_list:
                return False
            if self.potentials != other.potentials:
                return False
        except:
            return False

        return True

    def __ne__(self,other):
        return not self.__eq__(other)
            

    def __repr__(self):
        return "Pysic(atoms={atoms},potentials={pots},full_initialization={init})".format(atoms=str(self.structure),
                                                                                          pots=str(self.potentials),
                                                                                          init=str(self.force_core_initialization))


    def core_initialization_is_forced(self):
        """Returns true if the core is always fully initialized, false otherwise."""

        return self.force_core_initialization


    def force_core_initialization(self,new_mode):
        """Set the core initialization mode.

        Parameters:

        new_mode: logical
            true if full initialization is required, false if not
        """
        
        self.force_core_initialization = new_mode

    
    def calculation_required(self, atoms=None, 
                             quantities=['forces','energy','stress','electronegativities']):
        """Check if a calculation is required.
        
        When forces or energy are calculated, the calculator saves the
        result in case it is needed several times. This method tells
        if a wanted quantity is not yet calculated for the current
        structure and needs to be calculated explicitly. If a list of
        several quantities is given, the method returns true if any one of
        them needs to be calculated.
        
        Parameters:
        
        atoms: `ASE Atoms`_ object
            ignored at the moment
        quantities: list of strings
            list of keywords 'energy', 'forces', 'stress', 'electronegativities'
        """
        
        do_it = []
        try:
            assert isinstance(quantities, list)
            list_of_quantities = quantities
        except:
            list_of_quantities = [ quantities ]
        
        for mark in list_of_quantities:
            if mark == 'energy':
                do_it.append(self.energy is None)
            elif mark == 'forces':
                do_it.append(self.forces is None)
            elif mark == 'electronegativities':
                do_it.append(self.electronegativities is None)
            elif mark == 'stress':
                do_it.append(self.stress is None)
            else:
                do_it.append(False)
        
        # If the core does not match the Pysic calculator,
        # we may have changed the system or potentials
        # associated with the calculator without telling it.
        # In that case the quantities need to be recalculated.
        # It is of course possible that we have several Pysics
        # changing the core which would lead to unnecessary
        # recalculations.
        if(not Pysic.core.atoms_ready(self.structure)):
            #print "atoms"
            do_it.append(True)
        if(not Pysic.core.charges_ready(self.structure)):
            #print "charges"
            do_it.append(True)
        if(not Pysic.core.cell_ready(self.structure)):
            #print "cell"
            do_it.append(True)
        if(not Pysic.core.potentials_ready(self.potentials)):
            #print "potentials"
            do_it.append(True)
            
        return any(do_it)


    def get_atoms(self):
        """Returns the `ASE Atoms`_ object assigned to the calculator."""
        return self.structure


    def get_neighbor_lists(self):
        """Returns the :class:`~pysic.FastNeighborList` or `ASE NeighborList`_ 
        object assigned to the calculator.

        The neighbor lists are generated according to the given `ASE Atoms`_ object
        and the :class:`~pysic.Potential` objects of the calculator. Note that the lists
        are created when the core is set or if the method 
        :meth:`~pysic.Pysic.create_neighbor_lists` is called.
        """
        return self.neighbor_list


    def get_potentials(self):
        """Returns the list of potentials assigned to the calculator."""
        return self.potentials

    
    
    def get_electronegativities(self, atoms=None):
        """Returns the electronegativities of atoms.
        """
        self.set_atoms(atoms)
        if self.calculation_required(atoms,'electronegativities'):
            self.calculate_electronegativities()
        
        return self.electronegativities
    

    def get_electronegativity_differences(self, atoms=None):
        """Returns the electronegativity differences of atoms from the average of the entire system.
        """
        enegs = self.get_electronegativities(atoms)
        average_eneg = enegs.sum()/len(enegs)
        return enegs - average_eneg

    
    def get_forces(self, atoms=None):
        """Returns the forces.

        If the atoms parameter is given, it will be used for updating the
        structure assigned to the calculator prior to calculating the forces.
        Otherwise the structure already associated with the calculator is used.

        The calculator checks if the forces have been calculated already
        via :meth:`~pysic.Pysic.calculation_required`. If the structure
        has changed, the forces are calculated using :meth:`~pysic.Pysic.calculate_forces`

        Parameters:

        atoms: `ASE atoms`_ object
            the structure for which the forces are determined
        """
        self.set_atoms(atoms)
        if self.calculation_required(atoms,'forces'):
            self.calculate_forces()

        return self.forces


    def get_potential_energy(self, atoms=None, force_consistent=False):
        """Returns the potential energy.

        If the atoms parameter is given, it will be used for updating the
        structure assigned to the calculator prior to calculating the energy.
        Otherwise the structure already associated with the calculator is used.

        The calculator checks if the energy has been calculated already
        via :meth:`~pysic.Pysic.calculation_required`. If the structure
        has changed, the energy is calculated using :meth:`~pysic.Pysic.calculate_energy`

        Parameters:

        atoms: `ASE atoms`_ object
            the structure for which the energy is determined
        force_consistent: logical
            ignored at the moment
        """
        self.set_atoms(atoms)
        if self.calculation_required(atoms,'energy'):
            self.calculate_energy()

        return self.energy


    def get_stress(self, atoms=None):
        """Returns the stress tensor in the format 
        :math:`[\sigma_{xx},\sigma_{yy},\sigma_{zz},\sigma_{yz},\sigma_{xz},\sigma_{xy}]`

        If the atoms parameter is given, it will be used for updating the
        structure assigned to the calculator prior to calculating the stress.
        Otherwise the structure already associated with the calculator is used.

        The calculator checks if the stress has been calculated already
        via :meth:`~pysic.Pysic.calculation_required`. If the structure
        has changed, the stress is calculated using :meth:`~pysic.Pysic.calculate_stress`

        Stress (potential part) and force are evaluated in tandem. 
        Therefore, invoking the evaluation of
        one automatically leads to the evaluation of the other. Thus, if you have just
        evaluated the forces, the stress will already be known.
    
        This is because the
        stress tensor is formally defined as
            
        .. math::
        
            \\sigma_{AB} = -\\frac{1}{V} \\sum_i \\left[ m_i (v_i)_A (v_i)_B + (r_i)_A (f_i)_B \\right],
        
            
        where :math:`m`, :math:`v`, :math:`r`, and :math:`f` are mass, velocity,
        position and force of atom :math:`i`, and :math:`A`, :math:`B` denote the
        cartesian coordinates :math:`x,y,z`. 
        (The minus sign is there just to be consistent with the NPT routines in `ASE`_.) 
        However, if periodic boundaries are used,
        the absolute coordinates cannot be used (there would be discontinuities at the
        boundaries of the simulation cell). Instead, the potential energy terms 
        :math:`(r_i)_A (f_i)_B` must be evaluated locally for pair, triplet, and many
        body forces using the relative coordinates of the particles involved in the
        local interactions. These coordinates are only available during the actual force
        evaluation when the local interactions are looped over. Thus, calculating the stress
        requires doing the full force evaluation cycle. On the other hand, calculating the
        stress is not a great effort compared to the force evaluation, so it is convenient
        to evaluate the stress always when the forces are evaluated.
                        
        Parameters:

        atoms: `ASE atoms`_ object
            the structure for which the stress is determined
        """
        self.set_atoms(atoms)
        if self.calculation_required(atoms,'stress'):
            self.calculate_stress()
        
        # self.stress contains the potential contribution to the stress tensor
        # but we add the kinetic contribution on the fly
        momenta = self.structure.get_momenta()
        masses = self.structure.get_masses()
        velocities = np.divide( momenta, np.array([masses,masses,masses]).transpose() )

        kinetic_stress = np.array([0.0]*6)
        
        # s_xx, s_yy, s_zz, s_yz, s_xz, s_xy
        kinetic_stress[0] = np.dot( momenta[:,0], velocities[:,0] )
        kinetic_stress[1] = np.dot( momenta[:,1], velocities[:,1] )
        kinetic_stress[2] = np.dot( momenta[:,2], velocities[:,2] )
        kinetic_stress[3] = np.dot( momenta[:,1], velocities[:,2] )
        kinetic_stress[4] = np.dot( momenta[:,0], velocities[:,2] )
        kinetic_stress[5] = np.dot( momenta[:,0], velocities[:,1] )
                
        # ASE NPT simulator wants the pressure with an inversed sign
        return -( kinetic_stress + self.stress ) / self.structure.get_volume()

    
    def set_atoms(self, atoms=None):
        """Assigns the calculator with the given structure.
            
        This method is always called when any method is given the
        atomic structure as an argument. If the argument is missing
        or None, nothing is done. Otherwise a copy of the given structure
        is saved (according to the instructions in 
        `ASE API <https://wiki.fysik.dtu.dk/ase/ase/calculators/calculators.html#calculator-interface>`_.)
            
        If a structure is already in memory and it is different to the given
        one (as compared with ``__ne__``), it is noted that all quantities
        are unknown for the new system. If the structure is the same as the
        one already known, nothing is done.
        This is because if one wants to
        access the energy of forces of the same system repeatedly, it is unnecessary
        to always calculate them from scratch. Therefore the calculator saves
        the computed values along with a flag stating that the values have been
        computed.
            
        Parameters:

        atoms: `ASE atoms`_ object
            the structure to be calculated
        """
        if atoms == None:
            pass
        else:
            if(self.structure != atoms or
               (self.structure.get_charges() != atoms.get_charges()).any()):
                self.forces = None
                self.energy = None
                self.stress = None
                self.electronegativities = None
                

                # NB: this avoids updating the potential lists every time an atom moves
                try:
                    if((self.structure.get_atomic_numbers() != atoms.get_atomic_numbers()).any()):
                        Pysic.core.potential_lists_ready = False
                        self.neighbor_lists_waiting = False

                    if((self.structure.get_tags() != atoms.get_tags()).any()):
                        Pysic.core.potential_lists_ready = False
                        self.neighbor_lists_waiting = False                

                    if(not Pysic.core.potentials_ready(self.potentials)):
                        Pysic.core.potential_lists_ready = False
                        self.neighbor_lists_waiting = False

                except:
                    Pysic.core.potential_lists_ready = False
                    self.neighbor_lists_waiting = False
            

                self.structure = atoms.copy()


    def set_potentials(self, potentials):
        """Assign a list of potentials to the calculator.

        Parameters:

        potentials: list of :class:`~pysic.Potential` objects
            a list of potentials to describe interactinos
        """
        if potentials == None:
            pass
        else:
            self.forces = None
            self.energy = None
            self.stress = None
            self.electronegativities = None
            
            new_cutoffs = self.get_individual_cutoffs(1.0)
            self.neighbor_lists_waiting = not self.neighbor_lists_expanded(new_cutoffs)

            try:
                assert isinstance(potentials,list)
                self.potentials = potentials
            except:
                self.potentials = [potentials]
    
    
    def add_potential(self, potential):
        """Add a potential to the list of potentials.

        Parameters:

        potential: :class:`~pysic.Potential` object
            a new potential to describe interactions
        """

        if self.potentials == None:
            self.potentials = []

        self.potentials.append(potential)
        self.forces = None
        self.energy = None
        self.stress = None
        self.electronegativities = None
        new_cutoffs = self.get_individual_cutoffs(1.0)
        self.neighbor_lists_waiting = not self.neighbor_lists_expanded(new_cutoffs)
        
    
    def set_coulomb_summation(self,coulomb):
        """Set the Coulomb summation algorithm for the calculator.
            
            If a Coulomb summation algorithm is set, the Coulomb interactions
            between all charged atoms are evaluated automatically during
            energy and force evaluation. If not, the charges do not directly
            interact.
            
            Parameters:
            
            coulomb: :class:`~pysic.CoulombSummation`
                the Coulomb summation algorithm
            """
        self.coulomb = coulomb
        new_cutoffs = self.get_individual_cutoffs(1.0)
        self.neighbor_lists_waiting = not self.neighbor_lists_expanded(new_cutoffs)
    

    def get_coulomb_summation(self):
        """Returns the Coulomb summation algorithm of this calculator.
            """
        return self.coulomb
    
    
    def set_charge_relaxation(self,charge_relaxation):
        """Add a charge relaxation algorithm to the calculator.
            
            If a charge relaxation scheme has been added to the :class:`~pysic.Pysic`
            calculator, it will be automatically asked to do the charge relaxation 
            before the calculation of energies or forces via 
            :meth:`~pysic.ChargeRelaxation.charge_relaxation`.
            
            It is also possible to pass the :class:`~pysic.Pysic` calculator to the 
            :class:`~pysic.ChargeRelaxation` algorithm without creating the opposite
            link using :meth:`~pysic.ChargeRelaxation.set_calculator`. 
            In that case, the calculator does not automatically relax the charges, but
            the user can manually trigger the relaxation with 
            :meth:`~pysic.ChargeRelaxation.charge_relaxation`.
            
            If you wish to remove automatic charge relaxation, just call this method
            again with None as argument.
            
            Parameters:
            
            charge_relaxation: :class:`~pysic.ChargeRelaxation` object
                the charge relaxation algorithm
            """

        try:
            charge_relaxation.set_calculator(self, reciprocal=False)
        except:
            pass
        self.charge_relaxation = charge_relaxation

                
    def get_charge_relaxation(self):
        """Returns the :class:`~pysic.ChargeRelaxation` object connected to the calculator.
            """
        return self.charge_relaxation
    
    
    def create_neighbor_lists(self,cutoffs=None,marginal=neighbor_marginal):
        """Initializes the neighbor lists.

        In order to do calculations at reasonable speed, the calculator needs 
        a list of neighbors for each atom. For this purpose, the `ASE NeighborList`_
        are used. This method initializes these lists according to the given
        cutoffs.

        .. _ASE NeighborList: https://wiki.fysik.dtu.dk/ase/ase/calculators/calculators.html#building-neighbor-lists

        Parameters:

        cutoffs: list of doubles
            a list containing the cutoff distance for each atom
        marginal: double
            the skin width of the neighbor list
        """
        fastlist = True
        if cutoffs == None:
            cutoffs = self.get_individual_cutoffs(1.0)
        max_cut = np.max(cutoffs)
        
        for i in range(3):
            vec = self.structure.get_cell()[i]
            other_vec1 = self.structure.get_cell()[(i+1)%3]
            other_vec2 = self.structure.get_cell()[(i+2)%3]
            normal = np.cross(other_vec1,other_vec2)
            length = math.fabs(np.dot(vec,normal))/math.sqrt(np.dot(normal,normal))
            if length < max_cut:
                fastlist = False
                
        if fastlist:
            try:
                self.neighbor_list = FastNeighborList(cutoffs,skin=marginal)
            except:
                fastlist = False

        if not fastlist:
            self.neighbor_list = nbl.NeighborList(cutoffs,skin=marginal,sorted=False,self_interaction=False,bothways=True)

        self.neighbor_lists_waiting = True
        self.set_cutoffs(cutoffs)


    def get_individual_cutoffs(self,scaler=1.0):
        """Get a list of maximum cutoffs for all atoms.

        For each atom, the interaction with the longest cutoff is found and
        the associated maximum cutoffs are returned as a list. In case the a list
        of scaled values are required, the scaler can be adjusted. E.g., scaler = 0.5
        will return the cutoffs halved.

        Parameters:

        scaler: double
            a number for scaling all values in the generated list
        """
        if self.structure == None:
            return None
        elif self.potentials == None:
            if self.coulomb == None:
                return self.structure.get_number_of_atoms()*[0.0]
            else:
                return self.structure.get_number_of_atoms()*[self.coulomb.get_realspace_cutoff()]
        else:
            cuts = []
            # loop over all atoms, with symbol, tags, index containing the corresponding
            # info for a single atom at a time
            for symbol, tags, index in zip(self.structure.get_chemical_symbols(),
                                           self.structure.get_tags(),
                                           range(self.structure.get_number_of_atoms())):
            
                if self.coulomb == None:
                    max_cut = 0.0
                else:
                    max_cut = self.coulomb.get_realspace_cutoff()
                
                for potential in self.potentials:
                    active_potential = False
                    
                    if potential.get_different_symbols().count(symbol) > 0 or potential.get_different_tags().count(tags) > 0 or potential.get_different_indices().count(index) > 0:
                        active_potential = True
                    
                    if active_potential and potential.get_cutoff() > max_cut:
                        max_cut = potential.get_cutoff()

                    try:
                        for bond in potential.get_coordinator().get_bond_order_parameters():
                            active_bond = False
                            if bond.get_different_symbols().count(symbol) > 0:
                                active_bond = True
                                
                            if active_bond:
                                if bond.get_cutoff() > max_cut:
                                    max_cut = bond.get_cutoff()
                    except:
                        pass

                cuts.append(max_cut*scaler)
            return cuts


    def calculate_electronegativities(self):
        """Calculates electronegativities.
            
        Calls the Fortran core to calculate forces for the currently assigned structure.
        """
        self.set_core()
        n_atoms = pf.pysic_interface.get_number_of_atoms()
        self.electronegativities = pf.pysic_interface.calculate_electronegativities(n_atoms).transpose()
        
    
    def calculate_forces(self):
        """Calculates forces (and the potential part of the stress tensor).

        Calls the Fortran core to calculate forces for the currently assigned structure.
            
        If a link exists to a :class:`~pysic.ChargeRelaxation`, it is first made to
        relax the atomic charges before the forces are calculated.
        """
        self.set_core()
        if self.charge_relaxation != None:
            self.charge_relaxation.charge_relaxation()
        n_atoms = pf.pysic_interface.get_number_of_atoms()
        self.forces, self.stress = pf.pysic_interface.calculate_forces(n_atoms)#.transpose()
        self.forces = self.forces.transpose()
        

    def calculate_energy(self):
        """Calculates the potential energy.

        Calls the Fortran core to calculate the potential energy for the currently assigned structure.
 
        If a link exists to a :class:`~pysic.ChargeRelaxation`, it is first made to
        relax the atomic charges before the forces are calculated.
        """
        self.set_core()
        if self.charge_relaxation != None:
            self.charge_relaxation.charge_relaxation()
        n_atoms = pf.pysic_interface.get_number_of_atoms()
        self.energy = pf.pysic_interface.calculate_energy(n_atoms)


    def calculate_stress(self):
        """Calculates the potential part of the stress tensor (and forces).

        Calls the Fortran core to calculate the stress tensor for the currently assigned structure.
        """
        if self.charge_relaxation != None:
            self.charge_relaxation.charge_relaxation()
        
        self.set_core()
        n_atoms = pf.pysic_interface.get_number_of_atoms()
        self.forces, self.stress = pf.pysic_interface.calculate_forces(n_atoms)
        self.forces = self.forces.transpose()


    def set_core(self):
        """Sets up the Fortran core for calculation.

        If the core is not initialized, if the number of atoms has changed, or
        if full initialization is forced, the core is initialized from scratch.
        Otherwise, only the atomic coordinates and momenta are updated.
        Potentials, neighbor lists etc. are also updated if they have been edited.
        """        
        
        do_full_init = False
        if self.force_core_initialization:
            do_full_init = True
        elif not Pysic.core.mpi_ready:
            do_full_init = True
        elif Pysic.core.get_atoms() == None:
            do_full_init = True
        elif self.structure.get_number_of_atoms() != Pysic.core.structure.get_number_of_atoms():
            do_full_init = True
        elif self.structure.get_number_of_atoms() != pf.pysic_interface.get_number_of_atoms():
            do_full_init = True
            
                        
        if do_full_init:
            self.initialize_fortran_core()
        else:
            
            if not Pysic.core.cell_ready(self.structure):
                self.update_core_supercell()
            
            if not Pysic.core.atoms_ready(self.structure):
                self.update_core_coordinates()

            if not Pysic.core.charges_ready(self.structure):
                self.update_core_charges()
                    
            if not Pysic.core.potentials_ready(self.potentials):
                self.update_core_potentials()

            if self.coulomb != None:
                if not Pysic.core.coulomb_summation_ready(self.coulomb):
                    self.update_core_coulomb()
            
            if not Pysic.core.potential_lists_ready:
                self.update_core_potential_lists()

            if not self.neighbor_lists_waiting:
                self.create_neighbor_lists(self.get_individual_cutoffs(1.0))

            if not Pysic.core.neighbor_lists_ready(self.neighbor_list):
                self.update_core_neighbor_lists()
                

    def update_core_potential_lists(self):
        """Initializes the potential lists.

        Since one often runs :class:`~pysic.Pysic` with a set of potentials,
        the core pre-analyzes which potentials affect each atom and saves a list
        of such potentials for every particle. This method asks the core to
        generate these lists.
        """
        if not Pysic.core.atoms_ready(self.structure):
            raise MissingAtomsError("Creating potential lists before updating atoms in core.")
        pf.pysic_interface.create_potential_list()
        pf.pysic_interface.create_bond_order_factor_list()
        Pysic.core.potential_lists_ready = True


    def update_core_potentials(self):
        """Generates potentials for the Fortran core."""
                
        Pysic.core.potential_lists_ready = False
        if self.potentials == None:
            pf.pysic_interface.allocate_potentials(0)
            pf.pysic_interface.allocate_bond_order_factors(0)
            return

        if len(self.potentials) == 0:
            pf.pysic_interface.allocate_potentials(0)
            pf.pysic_interface.allocate_bond_order_factors(0)
            return
        
        n_pots = 0
        coord_list = []
        pot_index = 0
        # count the number of separate potentials
        for pot in self.potentials:

            # grab the coordinators associated with the potentials
            coord = pot.get_coordinator()
            if(coord != None):
                coord_list.append([coord,pot_index])
            pot_index += 1
            
            try:
                alltargets = pot.get_symbols()
                for targets in alltargets:
                    perms = permutations(targets)
                    different = set(perms)
                    n_pots += len(different)
            except:
                pass
            try:
                alltargets = pot.get_tags()
                for targets in alltargets:
                    perms = permutations(targets)
                    different = set(perms)
                    n_pots += len(different)
            except:
                pass
            try:
                alltargets = pot.get_indices()
                for targets in alltargets:
                    perms = permutations(targets)
                    different = set(perms)
                    n_pots += len(different)
            except:
                pass

        pf.pysic_interface.allocate_potentials(n_pots)

        pot_index = 0
        for pot in self.potentials:
            
            group_index = -1
            if pot.get_coordinator() != None:
                group_index = pot_index
                pot.get_coordinator().set_group_index(pot_index)
            pot_index += 1

            n_targ = pot.get_number_of_targets()
            no_symbs = np.array( n_targ*[pu.str2ints('xx',2)] ).transpose()
            no_tags = np.array( n_targ*[-9] )
            no_inds = np.array( n_targ*[-9] )

            try:
                alltargets = pot.get_symbols()
                for targets in alltargets:
                    int_orig_symbs = []
                    for orig_symbs in targets:
                        int_orig_symbs.append( pu.str2ints(orig_symbs,2) )

                    perms = permutations(targets)
                    different = set(perms)
                    for symbs in different:
                        int_symbs = []
                        for label in symbs:
                            int_symbs.append( pu.str2ints(label,2) )

                        pf.pysic_interface.add_potential(pot.get_potential_type(),
                                                         np.array( pot.get_parameter_values() ),
                                                         pot.get_cutoff(),
                                                         pot.get_soft_cutoff(),
                                                         np.array( int_symbs ).transpose(),
                                                         no_tags,
                                                         no_inds,
                                                         np.array( int_orig_symbs ).transpose(),
                                                         no_tags,
                                                         no_inds,
                                                         group_index )
            except:
                pass
            try:
                alltargets = pot.get_tags()
                for targets in alltargets:
                    orig_tags = targets
                    perms = permutations(targets)
                    different = set(perms)

                    for tags in different:
                        pf.pysic_interface.add_potential(pot.get_potential_type(),
                                                         np.array( pot.get_parameter_values() ),
                                                         pot.get_cutoff(),
                                                         pot.get_soft_cutoff(),
                                                         no_symbs,
                                                         np.array( tags ),
                                                         no_inds,
                                                         no_symbs,
                                                         np.array(orig_tags),
                                                         no_inds,
                                                         group_index )
            except:
                pass
            try:
                alltargets = pot.get_indices()                
                for targets in alltargets:
                    orig_inds = targets
                    perms = permutations(targets)
                    different = set(perms)

                    for inds in different:
                        pf.pysic_interface.add_potential(pot.get_potential_type(),
                                                         np.array( pot.get_parameter_values() ),
                                                         pot.get_cutoff(),
                                                         pot.get_soft_cutoff(),
                                                         no_symbs,
                                                         no_tags,
                                                         np.array( inds ),
                                                         no_symbs,
                                                         no_tags,
                                                         np.array(orig_inds),
                                                         group_index )
            except:
                pass

        n_bonds = 0
        for coord in coord_list:
            try:
                allbonds = coord[0].get_bond_order_parameters()
                for bond in allbonds:
                    alltargets = bond.get_symbols()
                    for targets in alltargets:
                        perms = permutations(targets)
                        different = set(perms)
                        n_bonds += len(different)
            except:
                pass

        pf.pysic_interface.allocate_bond_order_factors(n_bonds)

        for coord in coord_list:
            try:
                allbonds = coord[0].get_bond_order_parameters()
                for bond in allbonds:
                    alltargets = bond.get_symbols()
                    for targets in alltargets:

                        int_orig_symbs = []
                        for orig_symbs in targets:
                            int_orig_symbs.append( pu.str2ints(orig_symbs,2) )
                        
                        perms = permutations(targets)
                        different = set(perms)

                        for symbs in different:
                            int_symbs = []
                            for label in symbs:
                                int_symbs.append( pu.str2ints(label,2) )

                            pf.pysic_interface.add_bond_order_factor(bond.get_bond_order_type(),
                                                                   np.array( bond.get_parameters_as_list() ),
                                                                   np.array( bond.get_number_of_parameters() ),
                                                                   bond.get_cutoff(),
                                                                   bond.get_soft_cutoff(),
                                                                   np.array( int_symbs ).transpose(),
                                                                   np.array( int_orig_symbs ).transpose(),
                                                                   coord[1])

            except:
                pass


        n_atoms = pf.pysic_interface.get_number_of_atoms()
        pf.pysic_interface.allocate_bond_order_storage(n_atoms,
                                                       pot_index,
                                                       len(coord_list))

        Pysic.core.set_potentials(self.potentials)

            
    def update_core_coulomb(self):
        """Updates the Coulomb summation parameters in the Fortran core.
            """
        
        if self.coulomb != None:
            if self.coulomb.method == CoulombSummation.summation_modes[0]: # ewald summation
                rcut = self.coulomb.parameters['real_cutoff']
                kcut = self.coulomb.parameters['k_cutoff']
                sigma = self.coulomb.parameters['sigma']
                epsilon = self.coulomb.parameters['epsilon']
                
                scales = self.coulomb.get_scaling_factors()
                
                # calculate the truncation limits for the k-space sum
                reci_cell = self.structure.get_reciprocal_cell()
                volume = np.dot( reci_cell[0], np.cross( reci_cell[1], reci_cell[2] ) )
                k1 = int( kcut * np.linalg.norm( np.cross( reci_cell[1], reci_cell[2] ) ) / volume + 0.5 )
                k2 = int( kcut * np.linalg.norm( np.cross( reci_cell[0], reci_cell[2] ) ) / volume + 0.5 )
                k3 = int( kcut * np.linalg.norm( np.cross( reci_cell[0], reci_cell[1] ) ) / volume + 0.5 )

                if scales == None:
                    scales = [1.0]*self.structure.get_number_of_atoms()
                elif(len(scales) != self.structure.get_number_of_atoms()):
                    raise InvalidParametersError("Length of the scaling factor vector does not match the number of atoms.")
                
                pf.pysic_interface.set_ewald_parameters(rcut,
                                                        np.array([k1,k2,k3]),
                                                        sigma,
                                                        epsilon,
                                                        scales)

                Pysic.core.set_coulomb(self.coulomb)
        
    
    def update_core_coordinates(self):
        """Updates the positions and momenta of atoms in the Fortran core.

        The core must be initialized and the number of atoms must match.
        Upon the update, it is automatically checked if the neighbor lists
        should be updated as well.
        """
        
        if self.structure.get_number_of_atoms() != pf.pysic_interface.get_number_of_atoms():
            raise LockedCoreError("The number of atoms does not match.")
        
        positions = np.array( self.structure.get_positions() ).transpose()
        momenta = np.array( self.structure.get_momenta() ).transpose()

        self.forces = None
        self.energy = None
        self.stress = None
        self.electronegativities = None

        pf.pysic_interface.update_atom_coordinates(positions,momenta)

        Pysic.core.set_atomic_positions(self.structure)
        Pysic.core.set_atomic_momenta(self.structure)

        if not self.neighbor_lists_waiting:
            self.create_neighbor_lists(self.get_individual_cutoffs(1.0))
        
        self.update_core_neighbor_lists()

                    

    def update_core_charges(self):
        """Updates atomic charges in the core."""
        
        charges = np.array( self.structure.get_charges() )

        self.forces = None
        self.energy = None
        self.stress = None
        self.electronegativities = None
        
        pf.pysic_interface.update_atom_charges(charges)
        
        Pysic.core.set_charges(charges)
            
            
    def update_core_supercell(self):
        """Updates the supercell in the Fortran core."""
        vectors = np.array( self.structure.get_cell() ).transpose()
        inverse = np.linalg.inv(np.array( self.structure.get_cell() )).transpose()
        periodicity = np.array( self.structure.get_pbc() )
        
        pf.pysic_interface.create_cell(vectors,inverse,periodicity)
        
        Pysic.core.set_cell(self.structure)
        Pysic.core.set_neighbor_lists(None)
            

    def update_core_neighbor_lists(self):
        """Updates the neighbor lists in the Fortran core.

         If uninitialized, the lists are created first via :meth:`~pysic.Pysic.create_neighbor_lists`.
         """
        if not Pysic.core.atoms_ready(self.structure):
            raise MissingAtomsError("Creating neighbor lists before updating atoms in the core.")
        cutoffs = self.get_individual_cutoffs(1.0)
        if not self.neighbor_lists_waiting:
            self.create_neighbor_lists(cutoffs)
            self.set_cutoffs(cutoffs)
            self.neighbor_lists_waiting = True
    
        self.neighbor_list.update(self.structure)
    
        if isinstance(self.neighbor_list,FastNeighborList):
            # if we used the fast list, the core is already updated
            pass
        else:
            # if we have used the ASE list, it must be passed on to the core
            for index in range(self.structure.get_number_of_atoms()):
                [nbors,offs] = self.neighbor_list.get_neighbors(index)                
                pf.pysic_interface.create_neighbor_list(index+1,np.array(nbors),np.array(offs).transpose())

        Pysic.core.set_neighbor_lists(self.neighbor_list)
        

    def initialize_fortran_core(self):
        """Fully initializes the Fortran core, creating the atoms, supercell, potentials, and neighbor lists."""
        
        masses = np.array( self.structure.get_masses() )
        charges = np.array( self.structure.get_charges() )
        positions = np.array( self.structure.get_positions() ).transpose()
        momenta = np.array( self.structure.get_momenta() ).transpose()
        tags = np.array( self.structure.get_tags() )
        elements = self.structure.get_chemical_symbols()

        for index in range(len(elements)):
            elements[index] = pu.str2ints(elements[index],2)

        elements = np.array( elements ).transpose()

        #self.create_neighbor_lists(self.get_individual_cutoffs(1.0))
        #self.neighbor_lists_waiting = True

        pf.pysic_interface.create_atoms(masses,charges,positions,momenta,tags,elements)
        Pysic.core.set_atoms(self.structure)

        pf.pysic_interface.distribute_mpi(self.structure.get_number_of_atoms())
        Pysic.core.mpi_ready = True
                
        self.update_core_supercell()
        self.update_core_potentials()
        self.update_core_neighbor_lists()
        self.update_core_potential_lists()
        self.update_core_coulomb()



    def get_numerical_energy_gradient(self, atom_index, shift=0.0001, atoms=None):
        """Numerically calculates the negative gradient of energy with respect to moving a single particle.

        This is for debugging the forces."""

        if(atoms == None):
            system = self.structure
            orig_system = self.structure.copy()
        else:
            system = atoms.copy()
            orig_system = atoms.copy()
            self.set_atoms(system)
        
        self.energy == None
        energy_xp = self.get_potential_energy()
        system[atom_index].x += shift
        energy_xp = self.get_potential_energy()
        system[atom_index].x -= 2.0*shift
        energy_xm = self.get_potential_energy()
        system[atom_index].x += shift

        system[atom_index].y += shift
        energy_yp = self.get_potential_energy()
        system[atom_index].y -= 2.0*shift
        energy_ym = self.get_potential_energy()
        system[atom_index].y += shift

        system[atom_index].z += shift
        energy_zp = self.get_potential_energy()
        system[atom_index].z -= 2.0*shift
        energy_zm = self.get_potential_energy()
        system[atom_index].z += shift

        self.energy == None
        self.get_potential_energy(orig_system)
        
        return [ -(energy_xp-energy_xm)/(2.0*shift),
                 -(energy_yp-energy_ym)/(2.0*shift),
                 -(energy_zp-energy_zm)/(2.0*shift) ]


            
    def set_cutoffs(self, cutoffs):
        """Copy and save the list of individual cutoff radii.
            
            Parameters:
            
            cutoffs: list of doubles
            new cutoffs
            """
        self.saved_cutoffs = copy.deepcopy(cutoffs)
            
            
    def neighbor_lists_expanded(self, cutoffs):
        """Check if the cutoffs have been expanded.
                    
        If the cutoffs have been made longer than before,
        the neighbor lists have to be recalculated.
        This method checks the individual cutoffs of all atoms
        to check if the cutoffs have changed.
        
        Parameters:
        
        cutoffs: list of doubles
            new cutoffs
        """
        if self.saved_cutoffs == None:
            return True
        if cutoffs == None:
            return True
                                
        if len(self.saved_cutoffs) != len(cutoffs):
            return True
        for old_cut, new_cut in zip(self.saved_cutoffs, cutoffs):
            if old_cut < new_cut:
                return True
                
        return False

            


    def get_numerical_bond_order_gradient(self, coordinator, atom_index, moved_index, shift=0.001, atoms=None):
        """Numerically calculates the gradient of a bond order factor with respect to moving a single particle.

        This is for debugging the bond orders."""

        if(atoms == None):
            system = self.structure.copy()
            orig_system = self.structure.copy()
        else:
            system = atoms.copy()
            orig_system = atoms.copy()

        self.energy == None
        crd = coordinator
        system[moved_index].x += shift
        self.set_atoms(system)
        self.set_core()
        crd.calculate_bond_order_factors()
        bond_xp = crd.get_bond_order_factors()[atom_index]
        system[moved_index].x -= 2.0*shift
        self.set_atoms(system)
        self.set_core()
        crd.calculate_bond_order_factors()
        bond_xm = crd.get_bond_order_factors()[atom_index]
        system[moved_index].x += shift        

        system[moved_index].y += shift
        self.set_atoms(system)
        self.set_core()
        crd.calculate_bond_order_factors()
        bond_yp = crd.get_bond_order_factors()[atom_index]
        system[moved_index].y -= 2.0*shift
        self.set_atoms(system)
        self.set_core()
        crd.calculate_bond_order_factors()
        bond_ym = crd.get_bond_order_factors()[atom_index]
        system[moved_index].y += shift

        system[moved_index].z += shift
        self.set_atoms(system)
        self.set_core()
        crd.calculate_bond_order_factors()
        bond_zp = crd.get_bond_order_factors()[atom_index]
        system[moved_index].z -= 2.0*shift
        self.set_atoms(system)
        self.set_core()
        crd.calculate_bond_order_factors()
        bond_zm = crd.get_bond_order_factors()[atom_index]
        system[moved_index].z += shift

        self.energy == None
        self.set_atoms(orig_system)
        self.set_core()

        
        return [ (bond_xp-bond_xm)/(2.0*shift),
                 (bond_yp-bond_ym)/(2.0*shift),
                 (bond_zp-bond_zm)/(2.0*shift) ]



    
    def get_numerical_electronegativity(self, atom_index, shift=0.001, atoms=None):
        """Numerically calculates the derivative of energy with respect to charging a single particle.
            
            This is for debugging the electronegativities."""
        
        if(atoms == None):
            system = self.structure.copy()
            orig_system = self.structure.copy()
        else:
            system = atoms.copy()
            orig_system = self.structure.copy()
        
        charges = system.get_charges()
        self.energy == None
        self.set_atoms(system)
        self.set_core()
        charges[atom_index] += 1.0*shift
        system.set_charges(charges)
        energy_p = self.get_potential_energy(system)
        charges[atom_index] -= 2.0*shift
        system.set_charges(charges)
        energy_m = self.get_potential_energy(system)
        charges[atom_index] += 1.0*shift
        system.set_charges(charges)
        
        
        self.energy == None
        self.set_atoms(orig_system)
        self.set_core()
        
        return (energy_m-energy_p)/(2.0*shift)





