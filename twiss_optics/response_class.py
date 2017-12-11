"""
    Provides Class to get response matrces from Twiss parameters.
    The calculation is based on formulas in [1,2].

    Only works properly for on-orbit twiss files.

    Beta Beating Response:  Eq. A35 inserted into Eq. B45 in [1]
    Dispersion Response:    Eq. 26-27 in [1]
    Phase Advance Response: Eq. 28 in [1]
    Tune Response;          Eq. 7 in [2]

    [1]  A. Franchi et al.,
         Analytic formulas for the rapid evaluation of the orbit response matrix and chromatic
         functions from lattice parameters in circular accelerators
         NOT YET PUBLISHED

    [2]  R. Tomas, et al.,
         Review of linear optics measurement and correction for charged particle accelerators.
         Physical Review Accelerators and Beams, 20(5), 54801. (2017)
         https://doi.org/10.1103/PhysRevAccelBeams.20.054801

"""

import os
import json
import numpy as np
from Utilities import logging_tools as logtool
from Utilities import tfs_pandas as tfs
from Utilities.contexts import timeit
from Utilities import iotools
from twiss_optics import sequence_parser

from twiss_optics.twiss_functions import get_phase_advances, tau, dphi
from twiss_optics.twiss_functions import assertion, regex_in


LOG = logtool.get_logger(__name__, level_console=0)

EXCLUDE_CATEGORIES_DEFAULT = ["LQ", "MCBH", "MQX", "MQXT", "Q", "QIP15", "QIP2", "getListsByIR"]

class TwissResponse(object):

    ################################
    #            INIT
    ################################

    def __init__(self, seqfile_path, modelfile_path, varfile_path,
                 exclude_categories=EXCLUDE_CATEGORIES_DEFAULT,
                 at_elements='bpms'):

        self._twiss = self._get_model_twiss(modelfile_path)
        self._variables = self._read_variables(varfile_path, exclude_categories)
        self._var_to_el = self._get_variable_mapping(seqfile_path)
        self._elements_in = self._get_input_elements()
        self._elements_out = self._get_output_elements(at_elements)

        self._phase_advances = get_phase_advances(self._twiss)

        self._beta = self._calc_beta_response()
        self._dispersion = self._calc_dispersion_response()
        self._phase = self._calc_phase_advance_response()
        self._tune = self._calc_tune_response()

    @staticmethod
    def _get_model_twiss(modelfile_path):
        """ Load model, but keep only BPMs and Magnets """
        LOG.debug("Loading Model from file '{:s}'".format(modelfile_path))
        model = tfs.read_tfs(modelfile_path).set_index('NAME')
        LOG.debug("Removing non-necessary entries:")
        LOG.debug("  Entries total: {:d}".format(model.shape[0]))
        model = model.loc[regex_in(r"\A([MB]|" + model.SEQUENCE + r"\$START$)", model.index), :]
        LOG.debug("  Entries left: {:d}".format(model.shape[0]))
        return model

    @staticmethod
    def _read_variables(varfile_path, exclude_categories):
        """ Load variables list from json file """
        LOG.debug("Loading variables from file {:s}".format(varfile_path))

        with open(varfile_path, 'r') as varfile:
            var_dict = json.load(varfile)

        variables = []
        for category in var_dict.keys():
            if category not in exclude_categories:
                variables += var_dict[category]
        return list(set(variables))

    def _get_variable_mapping(self, seqfile_path):
        """ Get variable mapping as dictionary
            Call _read_variables before to set self._variables
        """
        LOG.debug("Converting variables to magnet names.")
        variables = self._variables
        mapping = sequence_parser.load_or_calc_variable_mapping(seqfile_path, "dictionary")

        for order in ("K0L", "K0SL", "K1L", "K1SL"):
            if order not in mapping:
                mapping[order] = {}

        # check if all variables can be found
        check_var = [var for var in variables
                     if all(var not in mapping[order] for order in mapping)]
        if len(check_var) > 0:
            raise ValueError("Variables '{:s}' cannot be found in sequence!".format(
                ", ".join(check_var)
            ))

        # drop mapping for unused variables
        [mapping[order].pop(var) for order in mapping for var in mapping[order].keys()
         if var not in variables]

        return mapping

    def _get_input_elements(self):
        """ Return variable names of input elements.
            Get variable mapping first!
        """
        v2e = self._var_to_el
        tw = self._twiss

        el_in = dict.fromkeys(v2e.keys())
        for order in el_in:
            el_order = []
            for var in v2e[order]:
                el_order += upper(v2e[order][var].index)
            el_in[order] = tw.loc[list(set(el_order)), "S"].sort_values().index.tolist()
        return el_in

    def _get_output_elements(self, at_elements):
        """ Return name-array of elements to use for output
            Define input elements first!
        """
        tw_idx = self._twiss.index

        if isinstance(at_elements, list):
            # elements specified
            if any(el not in tw_idx for el in at_elements):
                LOG.warning("One or more specified elements are not in the model.")
            return [idx for idx in tw_idx
                    if idx in at_elements]

        if at_elements == "bpms":
            # bpms only
            return [idx for idx in tw_idx
                    if idx.upper().startswith('B')]

        if at_elements == "bpms+":
            # bpms and the used magnets
            el_in = self._elements_in
            return [idx for idx in tw_idx
                    if (idx.upper().startswith('B')
                        or any(idx in el_in[order] for order in el_in))]

        if at_elements == "all":
            # all, obviously
            return tw_idx

    ################################
    #       Response Matrix
    ################################

    def _calc_beta_response(self):
        """ Response Matrix for delta betabeats
            Eq. A35 -> Eq. B45 in [1]
        """
        LOG.info("Calculate Beta Beating Response Matrix")
        with timeit(lambda t: LOG.debug("  Time needed: {:f}".format(t))):
            tw = self._twiss
            adv = self._phase_advances
            el_out = self._elements_out
            el_in = self._elements_in["K1L"]
            var2el = self._var_to_el["K1L"]
            dbetabeat = dict.fromkeys(["X", "Y"])

            dphix = dphi(adv["X"].loc[el_in, el_out], tw.Q1)
            dphiy = dphi(adv["Y"].loc[el_in, el_out], tw.Q2)

            dbetabeat["X"] = tfs.TfsDataFrame(
                -(1/(2*np.sin(2*np.pi*tw.Q1))) *
                  np.cos(2*np.pi*(2*dphix.values - tw.Q1)) *
                  tw.loc[el_in, ["BETX"]].values, index=el_in, columns=el_out).transpose()

            dbetabeat["Y"] = tfs.TfsDataFrame(
                (1 / (2 * np.sin(2 * np.pi * tw.Q2))) *
                np.cos(2 * np.pi * (2 * dphiy.values - tw.Q2)) *
                tw.loc[el_in, ["BETY"]].values, index=el_in, columns=el_out).transpose()

        return self._map_to_variables(dbetabeat, var2el)

    def _calc_dispersion_response(self):
        """ Response Matrix for delta dispersion
            Eq. 26-27 in [1]
        """
        LOG.info("Calculate Normalized Dispersion Response Matrix")
        with timeit(lambda t: LOG.debug("  Time needed: {:f}".format(t))):
            tw = self._twiss
            adv = self._phase_advances
            el_out = self._elements_out
            k0_el = self._elements_in["K0L"]
            j0_el = self._elements_in["K0SL"]
            j1_el = self._elements_in["K1SL"]
            var2k0 = self._var_to_el["K0L"]
            var2j0 = self._var_to_el["K0SL"]
            var2j1 = self._var_to_el["K1SL"]

            # Matrix N in Eq. 26
            if len(k0_el) > 0:
                taux = tau(adv["X"].loc[k0_el, el_out], tw.Q1)
                n = 1/(2*np.sin(np.pi * tw.Q1)) * \
                    np.sqrt(tw.loc[k0_el, ["BETX"]].values) * np.cos(2 * np.pi * taux)
                n_mapped = self._map_to_variables({"X": n.transpose()}, var2k0)
            else:
                LOG.debug("  No 'K0L' variables found. Dispersion Response 'X' will be empty.")
                n_mapped = {"X": tfs.TfsDataFrame(None, index=el_out)}

            # Matrix S(J0) in Eq. 26
            if len(j0_el) > 0:
                tauy_j0 = tau(adv["Y"].loc[j0_el, el_out], tw.Q2)
                sj0 = -1 / (2 * np.sin(np.pi * tw.Q2)) * \
                  np.sqrt(tw.loc[j0_el, ["BETY"]].values) * np.cos(2 * np.pi * tauy_j0)
                sj0_mapped = self._map_to_variables({"Y_J0": sj0.transpose()}, var2j0)
            else:
                LOG.debug("  No 'K0SL' variables found. Dispersion Response 'Y_J0' will be empty.")
                sj0_mapped = {"Y_J0": tfs.TfsDataFrame(None, index=el_out)}

            # Matrix S(J1) in Eq. 26
            if len(j1_el) > 0:
                tauy_j1 = tau(adv["Y"].loc[j1_el, el_out], tw.Q2)
                sj1 = -1 / (2 * np.sin(np.pi * tw.Q2)) * tw.loc[j1_el, ["DX"]].values * \
                  np.sqrt(tw.loc[j1_el, ["BETY"]].values) * np.cos(2 * np.pi * tauy_j1)
                sj1_mapped = self._map_to_variables({"Y_J1": sj1.transpose()}, var2j1)
            else:
                LOG.debug("  No 'K1SL' variables found. Dispersion Response 'Y_J1' will be empty.")
                sj1_mapped = {"Y_J1": tfs.TfsDataFrame(None, index=el_out)}

        return {"X": n_mapped["X"], "Y_J0": sj0_mapped["Y_J0"], "Y_J1": sj1_mapped["Y_J1"]}

    def _calc_phase_advance_response(self):
        """ Response Matrix for delta DPhi
            Eq. 28 in [1]
            Reduced to only phase advances between consecutive elements,
            as the 3D-Matrix of all elements exceeds memory space
            (~11000^3 = 1331 Giga Elements)
            --> w = j-1:  DPhi(z,j) = DPhi(x, (j-1)->j)
        """
        LOG.info("Calculate Phase Advance Response Matrix")
        with timeit(lambda t: LOG.debug("  Time needed: {:f}".format(t))):
            tw = self._twiss
            adv = self._phase_advances
            k1_el = self._elements_in["K1L"]
            var2el = self._var_to_el["K1L"]

            el_out_all = [tw.index[0]] + self._elements_out
            el_out = el_out_all[1:]  # in these we are actually interested
            el_out_mm = el_out_all[0:-1]  # first element is Sequence Start (MU = 0)

            if len(k1_el) > 0:
                dadv = dict.fromkeys(["X", "Y"])

                # sticking to the dimension order as in paper
                # so at the end there is a need to transpose the result for matrix multiplications
                pi = tfs.TfsDataFrame(tw['S'][:, None] < tw['S'][None, :],  # pi(i,j) = s(i) < s(j)
                                      index=tw.index, columns=tw.index, dtype=int)

                pi_term = pi.loc[k1_el, el_out].values - \
                          pi.loc[k1_el, el_out_mm].values + \
                          np.diag(pi.loc[el_out, el_out_mm].values)

                taux = tau(adv['X'].loc[k1_el, el_out_all], tw.Q1)
                tauy = tau(adv['Y'].loc[k1_el, el_out_all], tw.Q2)

                brackets_x = (2 * pi_term +
                             ((np.sin(4 * np.pi * taux.loc[:, el_out].values) -
                               np.sin(4 * np.pi * taux.loc[:, el_out_mm].values))
                              * 1 / np.sin(2 * np.pi * tw.Q1)))

                # hint: np can only broadcast ndarrays, which is values of a DF but not of a Series
                dadv['X'] = tfs.TfsDataFrame(
                            brackets_x * tw.loc[k1_el, ['BETX']].values * (1 / (8 * np.pi)),
                            index=k1_el, columns=el_out)

                brackets_y = (2 * pi_term +
                              ((np.sin(4 * np.pi * tauy.loc[:, el_out].values) -
                                np.sin(4 * np.pi * tauy.loc[:, el_out_mm].values))
                               * 1 / np.sin(2 * np.pi * tw.Q2)))

                # hint: np can only broadcast ndarrays, which is values of a DF but not of a Series
                dadv['Y'] = tfs.TfsDataFrame(
                            brackets_y * tw.loc[k1_el, ['BETY']].values * (1 / (8 * np.pi)),
                            index=k1_el, columns=el_out)

                # switching to total phase and proper axis orientation
                dmu = {
                    "X": dadv['X'].transpose().apply(np.cumsum),
                    "Y": dadv['Y'].transpose().apply(np.cumsum),
                }
                dmu_mapped = self._map_to_variables(dmu, var2el)
            else:
                LOG.debug("  No 'K1L' variables found. Phase Response will be empty.")
                dmu_mapped = {"X": tfs.TfsDataFrame(None, index=el_out),
                              "Y": tfs.TfsDataFrame(None, index=el_out)}

        return dmu_mapped

    def _calc_tune_response(self):
        """ Response vectors for Tune
            Eq. 7 in [2]
        """
        LOG.info("Calculate Tune Response Matrix")
        with timeit(lambda t: LOG.debug("  Time needed: {:f}".format(t))):
            tw = self._twiss
            k1_el = self._elements_in["K1L"]
            var2el = self._var_to_el["K1L"]

            if len(k1_el) > 0:
                dtune = dict.fromkeys(["X", "Y"])

                dtune["X"] = 1/(4 * np.pi) * tw.loc[k1_el, ["BETX"]].transpose()
                dtune["X"].index = ["DQX"]

                dtune["Y"] = -1 / (4 * np.pi) * tw.loc[k1_el, ["BETY"]].transpose()
                dtune["Y"].index = ["DQY"]

                dtune_mapped = self._map_to_variables(dtune, var2el)
            else:
                LOG.debug("  No 'K1L' variables found. Tune Response will be empty.")
                dtune_mapped = {"X": tfs.TfsDataFrame(None, index="DQX"),
                                "Y": tfs.TfsDataFrame(None, index="DQY")}

        return dtune_mapped

    @staticmethod
    def _map_to_variables(df_dict, mapping):
        """ Maps from magnets to variables using self._var_to_el.
            Could actually be done by matrix multiplication
            A * var_to_el, yet, as var_to_el is very sparse,
            looping is easier.

            :param df_dict: Dictionary (for planes) of dataframes to map
            :param mapping: mapping to be applied (e.g. var_to_el[order])
            :return: Dictionary (for planes) of mapped dataframes
        """
        mapped = dict.fromkeys(df_dict.keys())
        for plane in mapped:
            df_map = tfs.TfsDataFrame(index=df_dict[plane].index, columns=mapping.keys())
            for var, magnets in mapping.iteritems():
                df_map[var] = df_dict[plane].loc[:, upper(magnets.index)].mul(magnets.values,
                                                                axis="columns").sum(axis="columns")
            mapped[plane] = df_map
        return mapped

    ################################
    #          Getters
    ################################

    def get_beta_beat(self):
        """ Returns Response Matrix for Beta Beat """
        return self._beta

    def get_dispersion(self):
        """ Returns Response Matrix for Normalized Dispersion """
        return self._dispersion

    def get_phase(self):
        """ Returns Response Matrix for Total Phase """
        return self._phase

    def get_tune(self):
        """ Returns Response Matrix for the tunes """
        return self._tune

    def get_fullresponse(self):
        """ Returns all Response Matrices for the tunes """
        q_df = self._tune["X"].append(self._tune["Y"])
        q_df.index = ["Q1", "Q2"]

        return {
            "BBX": self._beta["X"],
            "BBY": self._beta["Y"],
            "MUX": self._phase["X"],
            "MUY": self._phase["Y"],
            "NDX": self._dispersion["X"],
            "NDY": (self._dispersion["Y_J0"], self._dispersion["Y_J1"]),
            "Q": q_df,
        }

    def get_variabel_names(self):
        return self._variables

    def get_variable_mapping(self, order=None):
        if order is None:
            return self._var_to_el
        else:
            return self._var_to_el[order]

################################
#          Other
################################


def upper(list_of_strings):
    return [item.upper() for item in list_of_strings]


def lower(list_of_strings):
    return [item.lower() for item in list_of_strings]


if __name__ == '__main__':
    root = iotools.get_absolute_path_to_betabeat_root()
    seq = os.path.join(root, 'twiss_optics', 'tests', 'lhcb1.seq')
    mod = os.path.join(root, 'twiss_optics', 'tests', 'twiss_dispersion.dat')
    var = os.path.join(root, 'MODEL', 'LHCB', 'fullresponse', 'LHCB1', 'AllLists.json')
    tr = TwissResponse(seq, mod, var)
    tr.get_fullresponse()