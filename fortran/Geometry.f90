!
! A module for handling the geometric structure of the system.
!
module geometry
  use quaternions
  use utility
  implicit none

  ! *label_length the number of characters available for denoting chemical symbols
  integer, parameter :: label_length = 2

  ! Defines a list of neighbors for a single atom.
  ! The list contains the indices of the neighboring atoms
  ! as well as the periodic boundary condition (PBC) offsets.
  !
  ! The offsets are integer
  ! triplets showing how many times must the supercell vectors
  ! be added to the position of the neighbor to find the
  ! neighboring image in a periodic system.
  ! For example, let the supercell be::
  !
  !  [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]],
  !
  ! i.e., a unit cube, with periodic boundaries.
  ! Now, if we have particles with coordinates::
  !
  !  a = [1.5, 0.5, 0.5]
  !  b = [0.4, 1.6, 3.3]
  ! 
  ! the closest separation vector :math:`\mathbf{r}_b-\mathbf{r}_a` between the particles is::
  !
  !   [-.1, .1, -.2]
  !
  ! obtained if we add the vector of periodicity::
  !
  !   [1.0, -1.0, -3.0]
  !
  ! to the coordinates of particle b. The offset vector
  ! (for particle b, when listing neighbors of a) is then::
  !
  !   [1, -1, -3]
  !
  ! Note that if the system is small, one atom can in
  ! principle appear several times in the neighbor list with
  ! different offsets.
  ! *neighbors indices of the neighboring atoms
  ! *pbc_offsets offsets for periodic boundaries for each neighbor
  ! *max_length The allocated length of the neighbor lists. To avoid deallocating and reallocating memory, extra space is reserved for the neighbors in case the number of neighbors increases during simulation (due to atoms moving).
  ! *n_neighbors the number of neighbors in the lists
  type neighbor_list
     integer, pointer :: neighbors(:), pbc_offsets(:,:)
     integer :: max_length, n_neighbors
  end type neighbor_list

  ! Defines an atomic particle.
  !
  ! *mass mass of th atom
  ! *charge charge of the atom
  ! *position coordinates of the atom
  ! *momentum momentum of the atom
  ! *index index of the atom
  ! *tags integer tag
  ! *n_pots number of potentials that may affect the atom
  ! *n_bonds number of bond order factors that may affect the atom
  ! *potentials_listed logical tag for checking if the potentials affecting the atom have been listed in potential_indices
  ! *bond_order_factors_listed logical tag for checking if the bond order factors affecting the atom have been listed in bond_indices
  ! *element the chemical symbol of the atom
  ! *neighbor_list the list of neighbors for the atom
  ! *potential_indices the indices of the potentials for which this atom is a valid target at first position (see :func:`potential_affects_atom`)
  ! *bond_indices the indices of the bond order factors for which this atom is a valid target at first position (see :func:`bond_order_factor_affects_atom`)
  ! *subcell_indices indices of the subcell containing the atom, used for fast neighbor searching (see :data:`subcell`)
  ! *max_potential_radius the maximum cutoff of any potential listed in potential_indices
  ! *max_bond_radius the maximum cutoff of any bond order factor listed in bond_indices
  type atom
     double precision :: mass, charge, position(3), momentum(3), &
          max_potential_radius, max_bond_radius
     integer :: index, tags, n_pots, n_bonds, subcell_indices(3)
     logical :: potentials_listed, bond_order_factors_listed
     character(len=label_length) :: element
     type(neighbor_list) :: neighbor_list
     integer, pointer :: potential_indices(:), bond_indices(:)
  end type atom

  ! Supercell containing the simulation.
  !
  ! The supercell is spanned by three vectors :math:`\mathbf{v}_1,\mathbf{v}_2,\mathbf{v}_3` stored as a 
  ! :math:`3 \times 3` matrix in format 
  ! 
  ! .. math::
  !
  !   \mathbf{M} = \left[ 
  !   \begin{array}{ccc}
  !   v_{1,x} & v_{1,y} & v_{1,z} \\
  !   v_{2,x} & v_{2,y} & v_{2,z} \\
  !   v_{3,x} & v_{3,y} & v_{3,z} 
  !   \end{array}
  !   \right].
  !
  ! Also the inverse cell matrix is kept for transformations between the absolute and fractional coordinates.
  !
  ! *vectors vectors spanning the supercell containing the system as a matrix :math:`\mathbf{M}`
  ! *inverse_cell the inverse of the cell matrix :math:`\mathbf{M}^{-1}`
  ! *reciprocal_cell the reciprocal cell as a matrix, :math:`\mathbf{M}_R = 2 \pi( \mathbf{M}^{-1} )^T`. That is, if :math:`\mathbf{b}_i` are the reciprocal lattice vectors and :math:`\mathbf{a}_j` the real space lattice vectors, then :math:`\mathbf{b}_i \mathbf{a}_j = 2 \pi \delta_{ij}`.
  ! *vector_lengths the lengths of the cell spanning vectors (stored to avoid calculating the vector norms over and over)
  ! *volume volume of the cell
  ! *periodic logical switch determining if periodic boundary conditions are applied in the directions of the three cell spanning vectors
  ! *n_splits the number of subcells there are in the subdivisioning of the cell, in the directions of the spanning vectors
  ! *max_subcell_atom_count the maximum number of atoms any of the subcells has
  ! *subcells an array of :data:`subcell` subvolumes which partition the supercell
  type supercell
     double precision :: vectors(3,3), inverse_cell(3,3), &
        reciprocal_cell(3,3),vector_lengths(3), volume
     logical :: periodic(3)
     integer :: n_splits(3), max_subcell_atom_count
     type(subcell), pointer :: subcells(:,:,:)
  end type supercell


  ! Subvolume, which is a part of the supercell containing the simulation.
  ! 
  ! The subcells are used in partitioning of the simulation space in subvolumes.
  ! This divisioning of the simulation cell is needed for quickly finding the 
  ! neighbors of atoms (see also :class:`pysic.FastNeighborList`).
  ! The fast neighbor search is based on dividing the system, locating the subcell
  ! in which each atom is located, and then searching for neighbors for each atom
  ! by only checking the adjacent subcells. For small subvolumes (short cutoffs)
  ! this method is much faster than a brute force algorithm that checks all atom
  ! pairs. It also scales :math:`\mathcal{O}(n)`.
  !
  ! *indices integer coordinates of the subcell in the subcell divisioning of the supercell
  ! *offsets integer offsets of the neighboring subcells - if a neighboring subcell is beyond a periodic border, the offset records the fact
  ! *n_atoms the number of atoms contained by the subcell
  ! *max_atoms the maximum number of atoms the cell can contain in the currently allocated memory space
  ! *vectors the vectors spanning the subcell
  ! *vector_lengths lengths of the vectors spanning the subcell
  ! *neighbors indices of the 3 x 3 x 3 neighboring subcells (note that the neighboring subcell 0,0,0 is the cell itself)
  ! *atoms indices of the atoms in this subcell
  ! *include A logical array noting if the neighboring subcells should be included in the neighbor search. Usually all neighbors are included, but in a non-periodic system, there is only a limited number of cells and once the system border is reached, this tag will be set to ``.false.`` to notify that there is no neighbor to be found.
  type subcell
     integer :: indices(3), offsets(3,-1:1,-1:1,-1:1), n_atoms, max_atoms
     double precision :: vectors(3,3), vector_lengths(3)
     integer :: neighbors(3,-1:1,-1:1,-1:1)
     integer, pointer :: atoms(:)
     logical :: include(-1:1,-1:1,-1:1)
  end type subcell

contains

  ! Creates the supercell containing the simulation geometry.
  !
  ! The supercell is spanned by three vectors :math:`\mathbf{v}_1,\mathbf{v}_2,\mathbf{v}_3` stored as a 
  ! :math:`3 \times 3` matrix in format 
  ! 
  ! .. math::
  !
  !   \mathbf{M} = \left[ 
  !   \begin{array}{ccc}
  !   v_{1,x} & v_{1,y} & v_{1,z} \\
  !   v_{2,x} & v_{2,y} & v_{2,z} \\
  !   v_{3,x} & v_{3,y} & v_{3,z} 
  !   \end{array}
  !   \right].
  !
  ! Also the inverse cell matrix :math:`\mathbf{M}^{-1}` must be given 
  ! for transformations between the absolute and fractional coordinates.
  ! However, it is not checked that the given matrix and inverse truly
  ! fulfill :math:`\mathbf{M}^{-1}\mathbf{M} = \mathbf{I}` - it is the
  ! responsibility of the caller to give the true inverse.
  !
  ! Also the periodicity of the system in the directions of the
  ! cell vectors need to be given.
  !
  ! *vectors the cell spanning matrix :math:`\mathbf{M}`
  ! *inverse the inverse cell :math:`\mathbf{M}`
  ! *periodicity logical switch, true if the boundaries are periodic
  ! *cell the created cell object
  subroutine generate_supercell(vectors,inverse,periodicity,cell)
    implicit none
    double precision, intent(in) :: vectors(3,3), inverse(3,3)
    logical, intent(in) :: periodicity(3)
    type(supercell), intent(out) :: cell
    integer :: i

    cell%vectors = vectors
    cell%inverse_cell = inverse
    cell%reciprocal_cell = 2*pi*transpose(inverse)
    cell%periodic = periodicity
    do i = 1, 3
       cell%vector_lengths(i) = (.norm.vectors(1:3,i))
    end do
    cell%volume = abs( (vectors(1:3,1).x.vectors(1:3,2)).o.vectors(1:3,3) )
    cell%n_splits = 0
    nullify(cell%subcells)

  end subroutine generate_supercell



  ! Creates atoms to construct the system to be simulated.
  !
  ! *n_atoms number of atoms
  ! *masses array of masses for the atoms
  ! *charges array of charges for the atoms
  ! *positions array of coordinates for the atoms
  ! *momenta array of momenta for the atoms
  ! *tags array of integer tags for the atoms
  ! *elements array of chemical symbols for the atoms
  ! *atoms array of the atom objects created
  subroutine generate_atoms(n_atoms,masses,charges,positions,momenta,tags,elements,atoms)
    implicit none
    integer, intent(in) :: n_atoms, tags(n_atoms)
    double precision, intent(in) :: masses(n_atoms), charges(n_atoms), positions(3,n_atoms), &
         momenta(3,n_atoms)
    character(len=label_length), intent(in) :: elements(n_atoms)
    type(atom), pointer :: atoms(:)
    integer :: i

    nullify(atoms)
    allocate(atoms(n_atoms))
    
    do i = 1, n_atoms
       atoms(i)%mass = masses(i)
       atoms(i)%charge = charges(i)
       atoms(i)%position(1:3) = positions(1:3,i)
       atoms(i)%momentum(1:3) = momenta(1:3,i)
       atoms(i)%tags = tags(i)
       atoms(i)%element = elements(i)
       atoms(i)%index = i
       atoms(i)%neighbor_list%max_length = 0
       atoms(i)%neighbor_list%n_neighbors = 0
       nullify(atoms(i)%neighbor_list%neighbors)
       nullify(atoms(i)%neighbor_list%pbc_offsets)
       atoms(i)%n_pots = 0
       atoms(i)%potentials_listed = .false.
       nullify(atoms(i)%potential_indices)
       atoms(i)%bond_order_factors_listed = .false.
       nullify(atoms(i)%bond_indices)
       atoms(i)%max_potential_radius = 0.d0
       atoms(i)%max_bond_radius = 0.d0
    end do

  end subroutine generate_atoms




  ! Updates the positions and momenta of the given atoms.
  ! Other properties are not altered. 
  !
  ! This is meant to be used
  ! during dynamic simulations or geometry optimization
  ! where the atoms are only moved around, not changed in other ways.
  !
  ! *n_atoms number of atoms
  ! *positions new coordinates for the atoms
  ! *momenta new momenta for the atoms
  ! *atoms the atoms to be edited
  subroutine update_atomic_positions(n_atoms,positions,momenta,atoms)
    implicit none
    integer, intent(in) :: n_atoms
    double precision, intent(in) :: positions(3,n_atoms), momenta(3,n_atoms)
    type(atom), pointer :: atoms(:)
    integer :: i

    if(size(atoms) /= n_atoms)then
       write(*,*) "the number of atoms has changed, you should reinitialize the structure"
    else
       do i = 1, n_atoms
          atoms(i)%position(1:3) = positions(1:3,i)
          atoms(i)%momentum(1:3) = momenta(1:3,i)
       end do
    end if

  end subroutine update_atomic_positions



  ! Updates the charges of the given atoms.
  ! Other properties are not altered. 
  !
  ! *n_atoms number of atoms
  ! *charges new charges for the atoms
  ! *atoms the atoms to be edited
  subroutine update_atomic_charges(n_atoms,charges,atoms)
    implicit none
    integer, intent(in) :: n_atoms
    double precision, intent(in) :: charges(n_atoms)
    type(atom), pointer :: atoms(:)
    integer :: i

    if(size(atoms) /= n_atoms)then
       write(*,*) "the number of atoms has changed, you should reinitialize the structure"
    else
       do i = 1, n_atoms
          atoms(i)%charge = charges(i)
       end do
    end if

  end subroutine update_atomic_charges



  ! Creates a neighbor list for one atom.
  !
  ! The neighbor list will contain an array of the indices
  ! of the neighboring atoms as well as periodicity offsets,
  ! as explained in :data:`neighbor_list`
  !
  ! The routine takes the neighbor_list object to be created
  ! as an argument. If the list is empty, it is initialized.
  ! If the list already contains information, the list is emptied and
  ! refilled. If the previous list has room to contain the new list
  ! (as in, it has enough allocated memory), no memory reallocation
  ! is done (since it will be slow if done repeatedly). Only if the
  ! new list is too long to fit in the reserved memory, the pointers
  ! are deallocated and reallocated.
  !
  ! *n_nbs number of neighbors
  ! *nbor_list The list of neighbors to be created.
  ! *neighbors array containing the indices of the neighboring atoms
  ! *offsets periodicity offsets
  subroutine assign_neighbor_list(n_nbs,nbor_list,neighbors,offsets)
    implicit none
    integer, intent(in) :: n_nbs
    integer, intent(in) :: neighbors(n_nbs), offsets(3,n_nbs)
    type(neighbor_list), intent(inout) :: nbor_list

    if(nbor_list%max_length <= n_nbs)then
       if(nbor_list%max_length > 0)then
          deallocate(nbor_list%neighbors)
          deallocate(nbor_list%pbc_offsets)
       else
          nullify(nbor_list%neighbors)
          nullify(nbor_list%pbc_offsets)
       end if
       allocate(nbor_list%neighbors(2*n_nbs+10))
       allocate(nbor_list%pbc_offsets(3,2*n_nbs+10))
       nbor_list%max_length = 2*n_nbs+10
    end if
    nbor_list%neighbors = -1
    nbor_list%pbc_offsets = 0
    nbor_list%n_neighbors = n_nbs
    if(n_nbs > 0)then
       nbor_list%neighbors(1:n_nbs) = neighbors(1:n_nbs)
       nbor_list%pbc_offsets(1:3,1:n_nbs) = offsets(1:3,1:n_nbs)
    end if

  end subroutine assign_neighbor_list

  ! Save the indices of potentials affecting an atom.
  !
  ! In force and energy evaluation, it is important to loop
  ! over potentials quickly. As the evaluation of energies
  ! goes over atoms, atom pairs etc., it is useful to first
  ! filter the potentials by the first atom participating 
  ! in the interaction. Therefore, the atoms can be given
  ! a list of potentials for which they are a suitable target
  ! as a 'first participant' (in a triplet A-B-C, A is the
  ! first participant).
  !
  ! *n_pots number of potentials
  ! *atom_in the atom for which the potentials are assigned
  ! *indices the indices of the potentials
  subroutine assign_potential_indices(n_pots,atom_in,indices)
    implicit none    
    integer, intent(in) :: n_pots
    type(atom), intent(inout) :: atom_in
    integer, intent(in) :: indices(n_pots)

    if(atom_in%potentials_listed)then
       if(atom_in%n_pots /= n_pots)then
          deallocate(atom_in%potential_indices)
          allocate(atom_in%potential_indices(size(indices)))
       end if
    else
       nullify(atom_in%potential_indices)
       allocate(atom_in%potential_indices(size(indices)))
    end if
    atom_in%potential_indices = indices
    atom_in%n_pots = size(indices)
    atom_in%potentials_listed = .true.

  end subroutine assign_potential_indices

  subroutine assign_max_potential_cutoff(atom_in, max_cut)
    implicit none
    double precision, intent(in) :: max_cut
    type(atom), intent(inout) :: atom_in

    atom_in%max_potential_radius = max_cut

  end subroutine assign_max_potential_cutoff


  subroutine assign_max_bond_order_factor_cutoff(atom_in, max_cut)
    implicit none
    double precision, intent(in) :: max_cut
    type(atom), intent(inout) :: atom_in

    atom_in%max_bond_radius = max_cut

  end subroutine assign_max_bond_order_factor_cutoff

  ! Save the indices of bond order factors affecting an atom.
  !
  ! In bond order factor evaluation, it is important to loop
  ! over bond parameters quickly. As the evaluation of factors
  ! goes over atoms, atom pairs etc., it is useful to first
  ! filter the parameters by the first atom participating 
  ! in the factor. Therefore, the atoms can be given
  ! a list of bond order parameters for which they are a suitable target
  ! as a 'first participant' (in a triplet A-B-C, A is the
  ! first participant).
  !
  ! *n_bonds number of bond order factors
  ! *atom_in the atom for which the bond order factors are assigned
  ! *indices the indices of the bond order factors
  subroutine assign_bond_order_factor_indices(n_bonds,atom_in,indices)
    implicit none    
    integer, intent(in) :: n_bonds
    type(atom), intent(inout) :: atom_in
    integer, intent(in) :: indices(n_bonds)

    if(atom_in%bond_order_factors_listed)then
       if(atom_in%n_bonds /= n_bonds)then
          deallocate(atom_in%bond_indices)
          allocate(atom_in%bond_indices(size(indices)))
       end if
    else
       nullify(atom_in%bond_indices)
       allocate(atom_in%bond_indices(size(indices)))
    end if
    atom_in%bond_indices = indices
    atom_in%n_bonds = size(indices)
    atom_in%bond_order_factors_listed = .true.

  end subroutine assign_bond_order_factor_indices




  ! Calculates the minimum separation vector between two atoms, :math:`\mathbf{r}_2-\mathbf{r}_1`, including possible periodicity.
  !
  ! *r1 coordiantes of atom 1, :math:`\mathbf{r}_1`
  ! *r2 coordinates of atom 1, :math:`\mathbf{r}_2`
  ! *offset periodicity offset (see :data:`neighbor_list`)
  ! *cell supercell spanning the system
  ! *separation the calculated separation vector, :math:`\mathbf{r}_2-\mathbf{r}_1`
  subroutine separation_vector(r1,r2,offset,cell,separation)
    implicit none
    double precision, intent(in) :: r1(3), r2(3)
    integer, intent(in) :: offset(3)
    type(supercell), intent(in) :: cell
    double precision, intent(out) :: separation(3)
    double precision :: wrap1(3), wrap2(3)
    integer :: i

    !call wrapped_coordinates(r1,cell,wrap1)
    !call wrapped_coordinates(r2,cell,wrap2)
    !separation = wrap2 - wrap1
    separation = r2 - r1
    do i = 1, 3
       separation = separation + offset(i)*cell%vectors(1:3,i)
    end do

  end subroutine separation_vector


  ! Transforms from absolute to fractional coordinates.
  !
  ! Absolute coordinates are the coordinates in the normal
  ! :math:`xyz` base,
  !
  ! .. math::
  ! 
  !    \mathbf{r} = x\mathbf{i} + y\mathbf{j} + z\mathbf{k}.
  !
  ! Fractional coordiantes are the coordiantes in the base
  ! spanned by the vectors defining the supercell, 
  ! :math:`\mathbf{v}_1`, :math:`\mathbf{v}_2`, :math:`\mathbf{v}_3`,
  !
  ! .. math::
  ! 
  !    \mathbf{r} = \tilde{x}\mathbf{v}_1 + \tilde{y}\mathbf{v}_2 + \tilde{z}\mathbf{v}_3.
  !
  ! Notably, for positions inside the supercell, the fractional 
  ! coordinates fall between 0 and 1.
  !
  ! Transformation between the two bases is given by the inverse cell 
  ! matrix
  !
  ! .. math::
  !
  !    \left[
  !    \begin{array}{c}
  !    \tilde{x} \\
  !    \tilde{y} \\
  !    \tilde{z}
  !    \end{array} \right] = \mathbf{M}^{-1}
  !    \left[
  !    \begin{array}{c}
  !    x \\
  !    y \\
  !    z
  !    \end{array} \right]
  !
  ! *position the absolute coordinates
  ! *cell the supercell
  ! *relative the fractional coordinates
  subroutine relative_coordinates(position,cell,relative)
    implicit none
    double precision, intent(in) :: position(3)
    type(supercell), intent(in) :: cell
    double precision, intent(out) :: relative(3)

    relative = matmul(cell%inverse_cell,position)

  end subroutine relative_coordinates


  ! Transforms from fractional to absolute coordinates.
  !
  ! Absolute coordinates are the coordinates in the normal
  ! :math:`xyz` base,
  !
  ! .. math::
  ! 
  !    \mathbf{r} = x\mathbf{i} + y\mathbf{j} + z\mathbf{k}.
  !
  ! Fractional coordiantes are the coordiantes in the base
  ! spanned by the vectors defining the supercell, 
  ! :math:`\mathbf{v}_1`, :math:`\mathbf{v}_2`, :math:`\mathbf{v}_3`,
  !
  ! .. math::
  ! 
  !    \mathbf{r} = \tilde{x}\mathbf{v}_1 + \tilde{y}\mathbf{v}_2 + \tilde{z}\mathbf{v}_3.
  !
  ! Notably, for positions inside the supercell, the fractional 
  ! coordinates fall between 0 and 1.
  !
  ! Transformation between the two bases is given by the cell 
  ! matrix
  !
  ! .. math::
  !
  !    \left[
  !    \begin{array}{c}
  !    x \\
  !    y \\
  !    z
  !    \end{array} \right] = \mathbf{M}
  !    \left[
  !    \begin{array}{c}
  !    \tilde{x} \\
  !    \tilde{y} \\
  !    \tilde{z}
  !    \end{array} \right]
  !
  ! *position the absolute coordinates
  ! *cell the supercell
  ! *relative the fractional coordinates
  subroutine absolute_coordinates(relative,cell,position)
    implicit none
    double precision, intent(out) :: position(3)
    type(supercell), intent(in) :: cell
    double precision, intent(in) :: relative(3)

    position = matmul(cell%vectors,relative)

  end subroutine absolute_coordinates


  ! Wraps a general coordinate inside the supercell if the system is periodic.
  !
  ! In a periodic system, every particle has periodic images at intervals
  ! defined by the cell vectors :math:`\mathbf{v}_1,\mathbf{v}_2,\mathbf{v}_3`.
  ! That is, for a particle at :math:`\mathbf{r}`, there are periodic
  ! images at
  !
  ! .. math::
  !
  !    \mathbf{R} = \mathbf{r} + a_1 \mathbf{v}_1 + a_2 \mathbf{v}_2 + a_3 \mathbf{v}_3
  !
  ! for all :math:`a_1, a_2, a_3 \in \mathbf{Z}`.
  ! These are equivalent positions in the sense that if a particle is 
  ! situated at any of one of them, the set of images is the same.
  ! Exactly one of the images is inside the cell - this routine gives
  ! the coordinates of that particular image.
  !
  ! If the system is periodic in only some directions, the wrapping is
  ! done only along those directions.
  !
  ! *position the absolute coordinates
  ! *cell the supercell
  ! *wrapped the wrapped absolute coordinates
  ! *offset wrapping offset, i.e., the number of times the cell vectors are added to the absolute coordinates in order to obtain the wrapped coordinates
  subroutine wrapped_coordinates(position,cell,wrapped,offset)
    implicit none
    double precision, intent(in) :: position(3)
    type(supercell), intent(in) :: cell
    double precision, intent(out) :: wrapped(3)
    integer, optional, intent(out) :: offset(3)
    double precision :: relative(3)
    integer :: i, off(3)
    
    off = 0
    call relative_coordinates(position,cell,relative)
    do i = 1, 3
       if( cell%periodic(i) )then
          off(i) = -floor(relative(i))
          relative(i) = relative(i) + off(i)
       end if
    end do
    call absolute_coordinates(relative,cell,wrapped)
    if(present(offset))then
       offset = off
    end if

  end subroutine wrapped_coordinates

  ! A utility function for sorting the atoms.
  !
  ! The function return ``true`` if ``index1 < index2`` and ``false`` otherwise.
  ! If ``index1 == index2``, the comparison is made through the separation vector.
  ! The vector is examined element at a time, and if a positive number is found,
  ! ``true`` is returned, if a negative one, ``false``. For values of zero, the next
  ! element is examined.
  !
  ! The purpose for this function is to sort the atoms to prevent double counting when summing 
  ! over pairs. In principle, a sum over pairs :math:`(i,j)` can be done with 
  ! :math:`\frac{1}{2} \sum_{i \ne j}`, but this leads to evaluation of all elements twice 
  ! (both :math:`(i,j)` and :math:`(j,i)` are considered separately).
  ! It is more efficient to evaluate :math:`\sum_{i < j}`, where only one of :math:`(i,j)` and :math:`(j,i)`
  ! fullfill the condition.
  !
  ! A special case arises if interactions are so long ranged that an atom can see its own periodic
  ! images. Then, one will need to sum terms for atom pairs where both atoms have the same index
  ! :math:`\sum_\mathrm{images} \sum_{i,j}` if they are in different periodic copies of the actual
  ! simulation cell. In order to still pick only one of the pairs :math:`(i,i')` and :math:`(i',i)`,
  ! we compare the offset vectors. If atom :math:`i'` is in the neighboring cell of :math:`i` in the
  ! first cell vector direction, it has an offset of :math:`[1,0,0]` and vice versa :math:`i` has
  ! an offset of :math:`[-1,0,0]` from :math:`i'`. Instead of the index, the sorting :math:`i' < i`
  ! is then done by comparing these offset vectors, element by element.
  !
  ! *index1 index of first atom
  ! *index2 index of second atom
  ! *offset pbc offset vector from atom1 to atom2
  function pick(index1,index2,offset)
    implicit none
    logical :: pick
    integer, intent(in) :: index1, index2
    integer, intent(in) :: offset(3)
    integer :: i

    pick = .false.
    if(index2 > index1)then
       pick = .true.
       return
    else if(index2 == index1 .and. offset(1) >= 0.d0)then
       if(offset(1) > 0.d0)then
          pick = .true.
          return
       else if(offset(1) == 0.d0)then
          if(offset(2) > 0.d0)then
             pick = .true.
             return
          else if(offset(2) == 0.d0)then
             if(offset(3) > 0.d0)then
                pick = .true.
                return
             end if
          end if          
       end if
    end if

  end function pick
  

  subroutine get_optimal_splitting(cell,max_cut,splits)
    implicit none
    type(supercell), intent(in) :: cell
    double precision, intent(in) :: max_cut
    integer, intent(out) :: splits(3)
    double precision :: normal(3), length
    integer :: i, v1, v2

    do i = 1,3
       v1 = mod(i,3)+1
       v2 = mod(i+1,3)+1
       
       ! the normal to the plane defined by the other two vectors
       normal = ((cell%vectors(1:3,v1)).x.(cell%vectors(1:3,v2)))
       ! the length of the projection of the vector on the normal
       length = abs( ((cell%vectors(1:3,i)).o.(normal)) ) / .norm.normal
       ! the number of times the length contains the cutoff
       if(max_cut < 0.1d-4)then ! there are probably no interactions...
          splits(i) = int( floor( 10.0*length ) )
       else
          splits(i) = int( floor( length/max_cut ) )
       end if
       ! do not split more than 40 times, otherwise we may end up using an enormous 
       ! amount of memory (100**3 = 1000000...)
       splits(i) = min(40, splits(i))

    end do

  end subroutine get_optimal_splitting


  ! Split the cell in subcells according to the given number of divisions.
  ! 
  ! The argument 'splits' should be a list of three integers determining how many
  ! times the cell is split. For instance, if splits = [3,3,5], the cell is divided in
  ! 3*3*5 = 45 subcells: 3 cells along the first two cell vectors and 5 along the third.
  ! 
  ! The Cell itself is not changed, but an array 'subcells' is created, containing
  ! the subcells which are Cell instances themselves. These cells will contain additional
  ! data arrays 'neighbors' and 'offsets'. These are 3-dimensional arrays with each dimension
  ! running from -1 to 1. The neighbors array contains references to the neighboring subcell
  ! Cell instances.
  ! The offsets contain coordinate offsets with respect to the periodic boundaries. In other words,
  ! if a subcell is at the border of the original Cell, it will have neighbors at the other side
  ! of the cell due to periodic boundary conditions. But from the point of view of the subcell,
  ! the neighboring cell is not on the other side of the master cell, but a periodic image of that
  ! cell. Therefore, any coordinates in the the subcell to which the neighbors array refers to must
  ! in fact be shifted by a vector of the master cell. The offsets list contains the multipliers
  ! for the cell vectors to make these shifts.
  !
  ! Example in 2D for simplicity: ``split = [3,4]`` creates subcells::
  !
  !  (0,3) (1,3) (2,3)
  !  (0,2) (1,2) (2,2)
  !  (0,1) (1,1) (2,1)
  !  (0,0) (1,0) (2,0)
  ! 
  ! subcell (0,3) will have the neighbors::
  !  (2,0) (0,0) (1,0)
  !  (2,3) (0,3) (1,3)
  !  (2,2) (0,2) (1,2)
  !
  ! and offsets::
  !  [-1,1] [0,1] [0,1]
  !  [-1,0] [0,0] [0,0]
  !  [-1,0] [0,0] [0,0]
  !
  ! Note that the central 'neighbor' is the cell itself.
  !
  ! If a boundary is not periodic, extra subcells with indices 0 and split+1
  ! are created to pad the simulation cell. These will contain the atoms that
  ! are outside the simulation cell.
  subroutine divide_cell(cell,splits)
    implicit none
    type(supercell), intent(inout) :: cell
    integer, intent(in) :: splits(3)
    double precision :: new_vecs(3,3), new_lengths(3)
    integer :: i,j,k, i_n,j_n,k_n, nbor_index(3), axis, offsets(3)

    if(cell%n_splits(1) == 0)then
       ! let every subcell have the initial capacity to store 20 atoms
       cell%max_subcell_atom_count = 20
       nullify(cell%subcells)
    else
       cell%max_subcell_atom_count = 20
       do k = 0, splits(3)+1
          do j = 0, splits(2)+1
             do i = 0, splits(1)+1
                if(cell%subcells(i,j,k)%max_atoms > 0)then
                   cell%max_subcell_atom_count = max(cell%max_subcell_atom_count,cell%subcells(i,j,k)%max_atoms)
                   deallocate(cell%subcells(i,j,k)%atoms)
                else
                   nullify(cell%subcells(i,j,k)%atoms)
                end if
             end do
          end do
       end do
       deallocate(cell%subcells)
    end if
    allocate(cell%subcells(0:splits(1)+1,0:splits(2)+1,0:splits(3)+1))

    cell%n_splits = splits

    ! the vectors spanning the subcells
    do i = 1,3
       new_vecs(1:3,i) = cell%vectors(1:3,i)/splits(i)
       new_lengths(i) = .norm.new_vecs(1:3,i)
    end do
    
    ! create subcells
    do k = 0, splits(3)+1
       do j = 0, splits(2)+1
          do i = 0, splits(1)+1

             cell%subcells(i,j,k)%indices = (/ i,j,k /)
             cell%subcells(i,j,k)%vectors = new_vecs
             cell%subcells(i,j,k)%vector_lengths = new_lengths
             allocate(cell%subcells(i,j,k)%atoms(cell%max_subcell_atom_count))
             cell%subcells(i,j,k)%atoms = -1
             cell%subcells(i,j,k)%n_atoms = 0
             cell%subcells(i,j,k)%max_atoms = cell%max_subcell_atom_count

          end do
       end do
    end do


    ! find neighbors of subcells
    do k = 0, splits(3)+1
       do j = 0, splits(2)+1
          do i = 0, splits(1)+1

             cell%subcells(i,j,k)%include = .true.

             ! loop over neighbors
             do k_n = -1,1
                do j_n = -1,1
                   do i_n = -1,1

                      ! plain neighbor indices
                      nbor_index(1) = i+i_n
                      nbor_index(2) = j+j_n
                      nbor_index(3) = k+k_n

                      ! initialize offsets and including/excluding tags
                      offsets = 0

                      ! loop over three directions and check for periodicity
                      do axis = 1,3

                         if(cell%periodic(axis))then

                            do while(nbor_index(axis) > splits(axis))
                               nbor_index(axis) = nbor_index(axis) - splits(axis)
                               offsets(axis) = offsets(axis) + 1
                            end do
                            do while(nbor_index(axis) < 1)
                               nbor_index(axis) = nbor_index(axis) + splits(axis)
                               offsets(axis) = offsets(axis) - 1
                            end do

                         else

                            ! if not periodic, make a note if the neighboring cell is non-existent
                            ! (out of bounds)
                            if(nbor_index(axis) < 0 .or. nbor_index(axis) > splits(axis)+1)then
                               cell%subcells(i,j,k)%include(i_n,j_n,k_n) = .false.
                               nbor_index(axis) = 0
                            end if

                         end if

                      end do ! do axis = 1, 3
                      
                      ! store indices to the adjacent subcells
                      cell%subcells(i,j,k)%neighbors(1:3,i_n,j_n,k_n) = nbor_index(1:3)
                      cell%subcells(i,j,k)%offsets(1:3,i_n,j_n,k_n) = offsets(1:3)

                   end do
                end do
             end do

          end do
       end do
    end do

  end subroutine divide_cell


  subroutine expand_subcell_atom_capacity(atoms_list,old_size,new_size)
    implicit none
    integer, pointer :: atoms_list(:)
    integer, intent(in) :: new_size, old_size
    integer :: tmp_list(old_size)

    tmp_list(1:old_size) = atoms_list(1:old_size)
    deallocate(atoms_list)
    allocate(atoms_list(new_size))
    atoms_list = -1
    atoms_list(1:old_size) = tmp_list(1:old_size)

  end subroutine expand_subcell_atom_capacity



  subroutine find_subcell_for_atom(cell,at)
    implicit none
    type(supercell), intent(inout) :: cell
    type(atom), intent(inout) :: at
    double precision :: wrapped(3), fractional(3), fractional2(3)
    integer :: i, indices(3)
    type(subcell), pointer :: thesubcell

    ! get the wrapped fractional coordinates
    call wrapped_coordinates(at%position,cell,wrapped)
    call relative_coordinates(wrapped,cell,fractional)

    ! get the indices of the subcells
    do i = 1,3
       if(cell%periodic(i))then
          indices(i) = mod( int(floor( fractional(i)*cell%n_splits(i) )), cell%n_splits(i) )+1
       else
          indices(i) = min( cell%n_splits(i)+1, max( 0, int(floor( fractional(i)*cell%n_splits(i) ))+1 ) )
       end if
    end do
    thesubcell => cell%subcells(indices(1),indices(2),indices(3))
    thesubcell%n_atoms = thesubcell%n_atoms+1
    thesubcell%atoms( thesubcell%n_atoms ) = at%index
    at%subcell_indices = indices

    ! if the storage capacity is full, expand the subcell atom list size
    if(thesubcell%n_atoms == thesubcell%max_atoms)then

       call expand_subcell_atom_capacity(thesubcell%atoms,&
            thesubcell%n_atoms, &
            thesubcell%max_atoms + 20)

       thesubcell%max_atoms = thesubcell%max_atoms + 20

       if(thesubcell%max_atoms > cell%max_subcell_atom_count)then
          cell%max_subcell_atom_count = thesubcell%max_atoms

       end if
    end if

  end subroutine find_subcell_for_atom


end module geometry
