from copy import copy

from wepy_tools.sim_makers.openmm import OpenMMToolsTestSysSimMaker

from wepy_tools.systems import receptor as receptor_tools

from wepy.resampling.distances.receptor import UnbindingDistance
from wepy.boundary_conditions.receptor import UnbindingBC

from wepy.util.json_top import (json_top_residue_fields,
                                json_top_residue_df,
                                json_top_atom_df,
                                json_top_subset)

from wepy.reporter.receptor.dashboard import (
    UnbindingBCDashboardSection,
)


import mdtraj as mdj
import numpy as np
import simtk.unit as unit

from openmmtools.testsystems import LysozymeImplicit

class LysozymeImplicitOpenMMSimMaker(OpenMMToolsTestSysSimMaker):

    TEST_SYS = LysozymeImplicit

    LIGAND_RESNAME = 'TMP'
    RECEPTOR_RES_IDXS = list(range(162))

    BCS = OpenMMToolsTestSysSimMaker.BCS + [UnbindingBC]

    UNBINDING_BC_DEFAULTS = {
        'cutoff_distance' : 1.0, # nm
    }

    DEFAULT_BC_PARAMS = OpenMMToolsTestSysSimMaker.DEFAULT_BC_PARAMS
    DEFAULT_BC_PARAMS.update(
        {
            'UnbindingBC' : UNBINDING_BC_DEFAULTS,
        }
    )

    def __init__(self, bs_cutoff=0.8*unit.nanometer):

        test_sys = LysozymeImplicit()

        init_state = self.make_state(test_sys.system, test_sys.positions)

        lig_idxs = self.ligand_idxs()
        bs_idxs = self.binding_site_idxs(bs_cutoff)

        distance = UnbindingDistance(ligand_idxs=lig_idxs,
                                     binding_site_idxs=bs_idxs,
                                     ref_state=init_state)


        super().__init__(
            distance=distance,
            init_state=init_state,
            system=test_sys.system,
            topology=test_sys.topology,
        )

    @classmethod
    def ligand_idxs(cls):

        json_top = cls.json_top()

        res_df = json_top_residue_df(json_top)
        residue_idxs = res_df[res_df['name'] == cls.LIGAND_RESNAME]['index'].values


        # get the atom dataframe and select them from the ligand residue
        atom_df = json_top_atom_df(json_top)
        atom_idxs = atom_df[atom_df['residue_key'].isin(residue_idxs)]['index'].values

        return atom_idxs

    @classmethod
    def receptor_idxs(cls):

        json_top = cls.json_top()

        # get the atom dataframe and select them from the ligand residue
        atom_df = json_top_atom_df(json_top)
        atom_idxs = atom_df[atom_df['residue_key'].isin(cls.RECEPTOR_RES_IDXS)]['index'].values

        return atom_idxs

    @classmethod
    def binding_site_idxs(cls, cutoff):

        test_sys = LysozymeImplicit()

        json_top = cls.json_top()

        atom_idxs = receptor_tools.binding_site_idxs(
            json_top,
            cls.ligand_idxs(),
            cls.receptor_idxs(),
            test_sys.positions,
            cls.box_vectors(),
            cutoff)

        return atom_idxs

    def choose_dashboard_sections(self, apparatus):

        dashboard_sections = super().choose_dashboard_sections(apparatus)

        if type(apparatus.boundary_conditions).__name__ == 'UnbindingBC':
            dashboard_sections['bc'] = UnbindingBCDashboardSection(apparatus.boundary_conditions)

        return dashboard_sections

    def make_bc(self, bc_class, bc_params):

        if bc_class == UnbindingBC:
            bc_params.update(
                {
                    'distance' : self.distance,
                    'initial_state' : self.init_state,
                    'topology' : self.json_top(),
                    'ligand_idxs' : self.ligand_idxs(),
                    'receptor_idxs' : self.receptor_idxs(),
                }
            )

        bc = bc_class(**bc_params)

        return bc
