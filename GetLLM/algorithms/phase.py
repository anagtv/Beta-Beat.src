'''
.. module: phase
Created on 27 May 2013

@author: ?, vimaier

@version: 0.0.1

GetLLM.algorithms.phase.py stores helper functions for phase calculations for GetLLM.
This module is not intended to be executed. It stores only functions.

Change history:
 - <version>, <author>, <date>:
    <description>
'''

import sys
import traceback
import math
import numpy as np
import compensate_excitation
from utils import tfs_file_writer
from model.accelerators.accelerator import AccExcitationMode
from constants import PI, TWOPI, kEPSILON
from utils import logging_tools

import pandas as pd
from time import time

DEBUG = sys.flags.debug # True with python option -d! ("python -d GetLLM.py...") (vimaier)
LOGGER = logging_tools.get_logger(__name__)

OPTIMISTIC = False

#---------------------------------------------------------------------------------------------------
# main part
#---------------------------------------------------------------------------------------------------

class PhaseData(object):
    ''' File for storing results from get_phases.
        Storing results from getphases_tot are not needed since values not used again.

        Attributes:
            ac2bpmac_x/_y: result of compensate_excitation.Get_AC2BPMAC for the H and V plane respectively.
            phase_advances_free_x/_y: the phase advances for the free motion. In case of a driven measurement this is
            compensated with Ryoichi's formula.
            phase_advances_x/_y: the phase advance without compensation.
            phase_advances_free2_x/_y: the phase advance calculated by the simple formula (rescaling).

    '''

    def __init__(self):
        self.ac2bpmac_x = None
        self.ac2bpmac_y = None

        self.phase_advances_x = None # horizontal phase
        self.phase_advances_free_x = None
        self.phase_advances_free2_x = None
        self.phase_advances_y = None # horizontal phase
        self.phase_advances_free_y = None
        self.phase_advances_free2_y = None


def calculate_phase(getllm_d, twiss_d, tune_d, files_dict):
    '''
    Calculates phase and fills the following TfsFiles:
        ``getphasex.out        getphasex_free.out        getphasex_free2.out``
        ``getphasey.out        getphasey_free.out        getphasey_free2.out``

    Parameters:
        getllm_d: the GetLLM_Data object including the accelerator class and the GetLLM options.
        twiss_d: includes measurement files and tunes (natural and driven if applicable, both measrued values)
        model: the model DataFrame representing the twiss parameters of the BPMs
        model_driven: the driven model
        elements: the model twiss with all the relevant elements
        files_dict: the files dict object which holds the GetLLM output file objects

    Returns:
        an instance of PhaseData filled with the results of this function.
        phase_d.phase_advances_x/y: pands.Panel filled with measured phase advances their errors and the model phase
        advances
        tune_d: tune_d.qa / tune_d.qaf for a in [1,2] are the vertical and horizontal natural and driven tunes

    Notes:
        The phase data will be a pandas.Panel with 3 dataframes ``MEAS``, ``MODEL``, ``ERRMEAS``

        ``phase_d.phase_advances_free_x[MEAS]``:

        +------++--------+--------+--------+--------+
        |      ||  BPM1  |  BPM2  |  BPM3  |  BPM4  | 
        +======++========+========+========+========+
        | BPM1 ||   0    | phi_12 | phi_13 | phi_14 | 
        +------++--------+--------+--------+--------+
        | BPM2 || phi_21 |    0   | phi_23 | phi_24 | 
        +------++--------+--------+--------+--------+
        | BPM3 || phi_31 | phi_32 |   0    | phi_34 | 
        +------++--------+--------+--------+--------+

        The phase advance between BPM_i and BPM_j can be obtained via::

            phi_ij = phi_j - phi_i = phase_advances.loc["MEAS", "BPM_j", "BPM_i"]
    '''
    # get accelerator and its model from getllm_d

    accelerator = getllm_d.accelerator
    try:
        model_free = accelerator.get_best_knowledge_model_tfs()
    except AttributeError:
        model_free = accelerator.get_model_tfs()
    if accelerator.excitation == AccExcitationMode.FREE:
        model_of_measurement = model_free
    else:
        model_of_measurement = accelerator.get_driven_tfs()
    model_elements = accelerator.get_elements_tfs()

    # get common bpms
    phase_d = PhaseData()
    if getllm_d.union:
        bpmsx = twiss_d.zero_dpp_unionbpms_x
        bpmsy = twiss_d.zero_dpp_unionbpms_y
    else:
        bpmsx = twiss_d.zero_dpp_commonbpms_x
        bpmsy = twiss_d.zero_dpp_commonbpms_y



    LOGGER.info('Calculating phase')

    # Info:
    LOGGER.info("t_value correction.................[YES]")
    if OPTIMISTIC:
        LOGGER.info("optimistic errorbars...............[YES]")
    else:
        LOGGER.info("optimistic errorbars...............[NO ]")
    union_text = "YES" if getllm_d.union else "NO"
    LOGGER.info("using all phase information........[{:3s}]".format(union_text))

    # --------------- Calculate tunes --------------------------------------------------------------

    if twiss_d.has_zero_dpp_x():
        #-- Calculate tune_x from files, weighted average based on rms
        q1_files = np.zeros(len(twiss_d.zero_dpp_x))
        q1_inv_Var = np.zeros(len(twiss_d.zero_dpp_x))
        for i, twiss_file in enumerate(twiss_d.zero_dpp_x):
            q1_files[i] = twiss_file.headers["Q1"]
            q1rms = twiss_file.headers["Q1RMS"]
            if q1rms == 0:
                q1rms = 1000
            q1_inv_Var[i] = 1.0 / float(q1rms) ** 2
        q1 = np.sum(q1_files * q1_inv_Var) / np.sum(q1_inv_Var)
        tune_d.q1 = q1
        tune_d.q1f = q1
        tune_d.q1mdlf = accelerator.nat_tune_x
        LOGGER.debug("horizontal tune of measurement files = {}".format(q1))

        phase_d.phase_advances_free_x, tune_d.mux = get_phases(
            getllm_d, model_of_measurement, twiss_d.zero_dpp_x, bpmsx, q1, 'H'
        )
        if not twiss_d.has_zero_dpp_y():
            LOGGER.warning('liny missing and output x only ...')


    if twiss_d.has_zero_dpp_y():
        #-- Calculate tune_x from files
        q2_files = np.zeros(len(twiss_d.zero_dpp_y))
        q2_inv_Var = np.zeros(len(twiss_d.zero_dpp_y))
        for i, twiss_file in enumerate(twiss_d.zero_dpp_y):
            q2_files[i] = twiss_file.headers["Q2"]
            q2rms = twiss_file.headers["Q2RMS"]
            if q2rms == 0:
                q2rms = 1000
            q2_inv_Var[i] = 1.0 / float(q2rms) ** 2
        q2 = np.sum(q2_files * q2_inv_Var) / np.sum(q2_inv_Var)
        tune_d.q2 = q2
        tune_d.q2f = q2
        tune_d.q2mdlf = accelerator.nat_tune_y
        LOGGER.debug("vertical tune of measurement files = {}".format(q2))

        phase_d.phase_advances_free_y, tune_d.muy = get_phases(
            getllm_d, model_of_measurement, twiss_d.zero_dpp_y, bpmsy, q2, 'V')
        if not twiss_d.has_zero_dpp_x():
            LOGGER.warning('linx missing and output y only ...')

    # ------------ Calculate the phases ------------------------------------------------------------

    #---- ac to free phase from eq and the model
    if getllm_d.accelerator.excitation != AccExcitationMode.FREE:
        if twiss_d.has_zero_dpp_x():
            tune_d.q1f = tune_d.q1 - getllm_d.accelerator.drv_tune_x + getllm_d.accelerator.nat_tune_x  # -- Free H-tune
            tune_d.q1mdl = accelerator.drv_tune_x
            # the calculation from before was actually wrong. But we keep the wrong values as phase_advances (why?)
            phase_d.phase_advances_x = phase_d.phase_advances_free_x 
            phase_d.ac2bpmac_x = compensate_excitation.GetACPhase_AC2BPMAC(
                bpmsx, tune_d.q1, tune_d.q1f, 'H', getllm_d.accelerator
            )
            [phase_d.phase_advances_free_x, tune_d.muxf] = compensate_excitation.get_free_phase_eq(
                model_free, twiss_d.zero_dpp_x, bpmsx, tune_d.q1, tune_d.q1f, phase_d.ac2bpmac_x,
                'H', model_free.Q1 % 1.0, getllm_d
            )
#            [phase_d.phase_advances_free2_x, tune_d.muxf2] = _get_free_phase(phase_d.phase_advances_free_x, tune_d.q1,
#            tune_d.q1f, bpmsx, model_driven, model, "H")
        if twiss_d.has_zero_dpp_y():
            phase_d.phase_advances_y = phase_d.phase_advances_free_y
            tune_d.q2f =  tune_d.q2 - getllm_d.accelerator.drv_tune_y + getllm_d.accelerator.nat_tune_y #-- Free V-tune
            tune_d.q2mdl = accelerator.drv_tune_y
            phase_d.ac2bpmac_y = compensate_excitation.GetACPhase_AC2BPMAC(
                bpmsy, tune_d.q2, tune_d.q2f, 'V', getllm_d.accelerator)
            [phase_d.phase_advances_free_y, tune_d.muyf] = compensate_excitation.get_free_phase_eq(
                model_free, twiss_d.zero_dpp_y, bpmsy, tune_d.q2, tune_d.q2f, phase_d.ac2bpmac_y,
                'V', model_free.Q2%1, getllm_d)
#            [phase_d.phase_advances_free2_y, tune_d.muyf2] = _get_free_phase(phase_d.phase_advances_free_y, tune_d.q2, tune_d.q2f, bpmsy, model_driven, model, "V")


    # ------------ Write the phases to file --------------------------------------------------------

    #---- H plane result
    LOGGER.debug("phase calculation finished. Write files.")
    if twiss_d.has_zero_dpp_x():
        LOGGER.debug("---- X output")
        files_dict["getphasex_free.out"] = write_phase_file(
            files_dict["getphasex_free.out"], "H", phase_d.phase_advances_free_x, model_free,
            model_elements, tune_d.q1f, tune_d.q2f, getllm_d.accelerator, getllm_d.union
        )
        files_dict["getphasetotx_free.out"] = write_phasetot_file(
            files_dict["getphasetotx_free.out"], "H", phase_d.phase_advances_free_x, model_free,
            model_elements, tune_d.q1f, tune_d.q2f, getllm_d.accelerator
        )
        #-- ac to free phase
        if getllm_d.accelerator.excitation != AccExcitationMode.FREE:
            #-- from eq
            files_dict["getphasex.out"] = write_phase_file(
                files_dict["getphasex.out"], "H", phase_d.phase_advances_x, model_free,
                model_elements, tune_d.q1, tune_d.q2, getllm_d.accelerator, getllm_d.union
            )
            files_dict["getphasetotx.out"] = write_phasetot_file(
                files_dict["getphasetotx.out"], "H", phase_d.phase_advances_x, model_free,
                model_elements, tune_d.q1, tune_d.q2, getllm_d.accelerator
            )

    #---- V plane result
    if twiss_d.has_zero_dpp_y():
        LOGGER.debug("---- Y output")
        files_dict["getphasey_free.out"] = write_phase_file(files_dict["getphasey_free.out"], "V",
                                                            phase_d.phase_advances_free_y, model_free, model_elements, tune_d.q1f,
                                                            tune_d.q2f, getllm_d.accelerator, getllm_d.union)
        files_dict["getphasetoty_free.out"] = write_phasetot_file(files_dict["getphasetoty_free.out"], "V",
                                                                  phase_d.phase_advances_free_y, model_free, model_elements,
                                                                  tune_d.q1f, tune_d.q2f, getllm_d.accelerator)
        #-- ac to free phase
        if getllm_d.accelerator.excitation != AccExcitationMode.FREE:
            #-- from eq
            files_dict["getphasey.out"] = write_phase_file(files_dict["getphasey.out"], "V", phase_d.phase_advances_y,
                                                           model_of_measurement, model_elements, tune_d.q1, tune_d.q2, getllm_d.accelerator,
                                                          getllm_d.union)
            files_dict["getphasetoty.out"] = write_phasetot_file(files_dict["getphasetoty.out"], "V",
                                                                 phase_d.phase_advances_y, model_free, model_elements, tune_d.q1,
                                                                 tune_d.q2, getllm_d.accelerator)

    return phase_d, tune_d
# END calculate_phase -------------------------------------------------------------------------------------------------

#---------------------------------------------------------------------------------------------------
# helper-functions
#---------------------------------------------------------------------------------------------------

def t_value_correction(_num):
    ''' Calculations are based on Hill, G. W. (1970)
    Algorithm 396: Student's t-quantiles. Communications of the ACM, 
    13(10), 619-620.

    http://en.wikipedia.org/wiki/Quantile_function#The_Student.27s_t-distribution

    It is not implemented directly here because a library for the erfinv() function, the inverse error function
    cannot be accessed from our servers in their current python installation (Jan-2015).
    (http://en.wikipedia.org/wiki/Error_function#Inverse_function)
    '''
    num = int(_num)
    correction_dict = {2:1.8394733927562799, 3:1.3224035682262103, 4:1.1978046912864673, 
                       5:1.1424650980932523, 6:1.1112993008590089, 7:1.0913332519214189, 
                       8:1.0774580800762166, 9:1.0672589736833817, 10:1.0594474783177483,
                       11:1.053273802733051, 12:1.0482721313740653, 13:1.0441378866779087,
                       14:1.0406635564353071, 15:1.0377028976401199, 16:1.0351498875115406,
                       17:1.0329257912610941, 18:1.0309709166064416, 19:1.029239186837585, 
                       20:1.0276944692596461}
    if num > 1 and num <=20:
        t_factor = correction_dict[num]
    else:
        t_factor = 1
    return t_factor

# vectorizing the function in order to be able to apply it to a matrix
vec_t_value_correction = np.vectorize(t_value_correction, otypes=[int])

def calc_phase_mean(phase0, norm):
    ''' phases must be in [0,1) or [0,2*pi), norm = 1 or 2*pi '''
    # look at hole_in_one/get_optics_3D.py !!!!!!!!!!
    phase0 = np.array(phase0)%norm
    phase1 = (phase0 + .5*norm) % norm - .5*norm
    phase0ave = np.mean(phase0)
    phase1ave = np.mean(phase1)
    # Since phase0std and phase1std are only used for comparing, I modified the expressions to avoid
    # math.sqrt(), np.mean() and **2.
    # Old expressions:
    #     phase0std = math.sqrt(np.mean((phase0-phase0ave)**2))
    #     phase1std = math.sqrt(np.mean((phase1-phase1ave)**2))
    # -- vimaier
    mod_phase0std = sum(abs(phase0-phase0ave))
    mod_phase1std = sum(abs(phase1-phase1ave))
    if mod_phase0std < mod_phase1std:
        return phase0ave
    else:
        return phase1ave % norm

def calc_phase_std(phase0, norm):
    ''' phases must be in [0,1) or [0,2*pi), norm = 1 or 2*pi '''
    phase0 = np.array(phase0)%norm
    phase1 = (phase0 + .5*norm) % norm - .5*norm
    phase0ave = np.mean(phase0)
    phase1ave = np.mean(phase1)

    # Omitted unnecessary computations. Old expressions:
    #     phase0std=sqrt(mean((phase0-phase0ave)**2))
    #     phase1std=sqrt(mean((phase1-phase1ave)**2))
    #     return min(phase0std,phase1std)
    # -- vimaier
    phase0std_sq = np.sum((phase0-phase0ave)**2)
    phase1std_sq = np.sum((phase1-phase1ave)**2)

    min_phase_std = min(phase0std_sq, phase1std_sq)
    if len(phase0) > 1:
        phase_std = math.sqrt(min_phase_std/(len(phase0)-1))
        phase_std = phase_std * t_value_correction(len(phase0)-1)
    else:
        phase_std = 0
    return phase_std

def get_phases(getllm_d, mad_twiss, Files, bpm, tune_q, plane):
    """
    Calculates phase.
    tune_q will be used to fix the phase shift in LHC.

    ``phase_advances["MEAS"]`` contains the measured phase advances.

    ``phase_advances["MODEL"]`` contains the model phase advances.

    ``phase_advances["ERRMEAS"]`` contains the error of the measured phase advances as deterined by
    the standard deviation scaled by sqrt(number_of_files).::

        phase_advances.loc["MEAS", bpm_namei, bpm_namej]

    yields the phase advance ``phi_ij`` between BPMi and BPMj
    """
    acc = getllm_d.accelerator
    plane_mu = "MUX" if plane == "H" else "MUY"
    bd = acc.get_beam_direction()
    number_commonbpms = bpm.shape[0]
    muave = 0  # TODO: find out what this is and who needs it

    #-- Last BPM on the same turn to fix the phase shift by Q for exp data of LHC
    if getllm_d.lhc_phase == "1":

        k_lastbpm = acc.get_k_first_BPM(bpm.index)
    else:
        print "phase jump will not be corrected"
        k_lastbpm = len(bpm.index)

    if getllm_d.union:
        phase_advances = _get_phases_union(
            bpm, bd, plane_mu, mad_twiss, Files, k_lastbpm)
    else:
        phase_advances = _get_phases_intersection(
            bpm, number_commonbpms, bd, plane_mu, mad_twiss, Files, k_lastbpm, tune_q)

    return phase_advances, muave


def _get_phases_intersection(bpm, number_commonbpms, bd, plane_mu, mad_twiss, Files, k_lastbpm,
                             tune_q):
    """Calculates the phases when the intersection of BPMs is used instead of a selective
    intersection.

    Note:
        Circular average and circular standard deviations are used as described in
        https://en.wikipedia.org/wiki/Directional_statistics.
    """

    # pandas panel that stores the model phase advances, measurement phase advances and meas. errors
    phase_advances = pd.Panel(
        items=["MODEL", "MEAS", "ERRMEAS", "NFILES"],
        major_axis=bpm.index, minor_axis=bpm.index)

    phases_mdl = np.array(mad_twiss.loc[bpm.index, plane_mu])
    phase_advances["MODEL"] = (phases_mdl[np.newaxis, :] - phases_mdl[:, np.newaxis])%1

    # loop over the measurement files
    phase_matr_meas = np.empty((len(Files), number_commonbpms, number_commonbpms))
    sin_phase_matr_meas = np.zeros((number_commonbpms, number_commonbpms))
    cos_phase_matr_meas = np.zeros((number_commonbpms, number_commonbpms))
    for i, file_tfs in enumerate(Files):
        phases_meas = bd * np.array(file_tfs.loc[bpm.index, plane_mu])
        phases_meas[k_lastbpm+1:] += tune_q  * bd
        meas_matr = (phases_meas[np.newaxis, :] - phases_meas[:, np.newaxis])
        phase_matr_meas[i] = np.where(
            abs(phase_advances["MODEL"]) > .5,
            meas_matr + .5,
            meas_matr)
        phase_matr_meas[i] = meas_matr
        sin_phase_matr_meas += np.sin(meas_matr * TWOPI)
        cos_phase_matr_meas += np.cos(meas_matr * TWOPI)

    phase_advances["NFILES"] = len(Files)

    phase_advances["MEAS"] = (np.arctan2(sin_phase_matr_meas / len(Files), cos_phase_matr_meas /
                                         len(Files)) / TWOPI) % 1

    if OPTIMISTIC:
        R = np.sqrt(
            (sin_phase_matr_meas * sin_phase_matr_meas + cos_phase_matr_meas * cos_phase_matr_meas)
            ) / len(Files)
        phase_advances["ERRMEAS"] = np.sqrt(-2.0 * np.log(R)) / np.sqrt(len(Files))
    else:
        R = np.sqrt(
            (sin_phase_matr_meas * sin_phase_matr_meas + cos_phase_matr_meas * cos_phase_matr_meas)
            ) / len(Files)
        phase_advances["ERRMEAS"] = np.sqrt(-2.0 * np.log(R))

    return phase_advances


def _get_phases_union(bpm, bd, plane_mu, mad_twiss, Files, k_lastbpm):
    """Calculate the phase advances for a selective intersection of BPMS.

    Note:
        Circular average and circular standard deviations are used as described in
        https://en.wikipedia.org/wiki/Directional_statistics.

        The name "union" may be misleading. It is more a "selective intersection"
    """

    LOGGER.debug("calculating phases with union of measurement files")
    LOGGER.debug("maximum {:d} measurements per BPM".format(len(Files)))
    # pandas panel that stores the model phase advances, measurement phase advances and meas. errors
    phase_advances = pd.Panel(
        items=["MODEL", "MEAS", "ERRMEAS", "NFILES"],
        major_axis=bpm.index, minor_axis=bpm.index)

    phases_mdl = np.array(mad_twiss.loc[bpm.index, plane_mu])
    phase_advances["MODEL"] = (phases_mdl[np.newaxis, :] - phases_mdl[:, np.newaxis]) % 1.0

    # loop over the measurement files
    phase_matr_meas = pd.Panel(items=range(len(Files)), major_axis=bpm.index, minor_axis=bpm.index)
    #phase_matr_count = pd.Panel(items=range(len(Files)), major_axis=bpm.index, minor_axis=bpm.index)
    for i in range(len(Files)):
        file_tfs = Files[i]
        phases_meas = bd * np.array(file_tfs.loc[:, plane_mu]) #-- bd flips B2 phase to B1 direction
        #phases_meas[k_lastbpm:] += tune_q  * bd
        
        meas_matr = (phases_meas[np.newaxis,:] - phases_meas[:,np.newaxis]) 
        phase_matr_meas.loc[i] = pd.DataFrame(data=np.where(meas_matr > 0, meas_matr, meas_matr + 1.0),
                                              index=file_tfs.index, columns=file_tfs.index)
        
    phase_matr_meas = phase_matr_meas.values
    mean = np.nanmean(phase_matr_meas, axis=0) % 1.0
    phase_advances["MEAS"] = mean
    nfiles = np.sum(~np.isnan(phase_matr_meas), axis=0)
    
    phase_advances["NFILES"] = nfiles
    if OPTIMISTIC:
        phase_advances["ERRMEAS"] = np.nanstd(phase_matr_meas, axis=0) / np.sqrt(nfiles) * vec_t_value_correction(nfiles)
    else:
        phase_advances["ERRMEAS"] = np.nanstd(phase_matr_meas, axis=0) * vec_t_value_correction(nfiles)


    return phase_advances

#---------------------------------------------------------------------------------------------------
# output
#---------------------------------------------------------------------------------------------------

def write_phase_file(tfs_file, plane, phase_advances, model, elements, tune_x, tune_y, accel, union):
    """Writes the phase advances into a file. Important phase advances are written into the header.
    """
    
    plane_char = "X" if plane == "H" else "Y"
    plane_mu = "MU" + plane_char
    plane_tune = tune_x if plane == "H" else tune_y
    
    tfs_file.add_float_descriptor("Q1", tune_x)
    tfs_file.add_float_descriptor("Q2", tune_y)
    tfs_file.add_column_names(["NAME", "NAME2", "S", "S1", "PHASE" + plane_char, "STDPH" + plane_char,
                               "PH{}MDL".format(plane_char), "MU{}MDL".format(plane_char), "COUNT"])
    tfs_file.add_column_datatypes(["%s", "%s", "%le", "%le", "%le", "%le", "%le", "%le", "%le"])

    if OPTIMISTIC:
        tfs_file.add_string_descriptor("OptimisticErrorBars", "True")
    else:
        tfs_file.add_string_descriptor("OptimisticErrorBars", "False")

    meas = phase_advances["MEAS"]
    mod = phase_advances["MODEL"]
    err = phase_advances["ERRMEAS"]

    nfiles = phase_advances["NFILES"]
    bd = accel.get_beam_direction()
    
    intersected_model = model.loc[meas.index]

    for elem1, elem2 in accel.get_important_phase_advances():

        mus1 = elements.loc[elem1, plane_mu] - elements.loc[:, plane_mu]
        minmu1 = abs(mus1.loc[meas.index]).idxmin()
        
        mus2 = elements.loc[:, plane_mu] - elements.loc[elem2, plane_mu]
        minmu2 = abs(mus2.loc[meas.index]).idxmin()
        
        try:
            bpm_phase_advance = meas.loc[minmu1, minmu2]
            model_value = elements.loc[elem2, plane_mu] - elements.loc[elem1, plane_mu]

            if (elements.loc[elem1, "S"] - elements.loc[elem2, "S"]) * bd > 0.0:
                bpm_phase_advance += plane_tune
                model_value += plane_tune
            bpm_err = err.loc[minmu1, minmu2]
            phase_to_first = -mus1.loc[minmu1]
            phase_to_second = -mus2.loc[minmu2]

            ph_result = ((bpm_phase_advance + phase_to_first + phase_to_second) * bd)
            model_value = (model_value * bd)

            resultdeg = ph_result % .5 * 360
            if resultdeg > 90:
                resultdeg -= 180

            modeldeg = model_value % .5 * 360
            if modeldeg > 90:
                modeldeg -= 180

            model_desc = [elem1 + "__to__" + elem2 + "___MODL",
                          "{:8.4f}     {:6s} = {:6.2f} deg".format(model_value % 1, "",
                                                                   modeldeg)]
            result_desc = [elem1 + "__to__" + elem2 + "___MEAS",
                           "{:8.4f}  +- {:6.4f} = {:6.2f} +- {:3.2f} deg ({:8.4f} + {:8.4f} [{}, {}])".format(
                               ph_result % 1, bpm_err, resultdeg, bpm_err * 360,
                               bpm_phase_advance,
                               phase_to_first + phase_to_second,
                               minmu1, minmu2) ]

            tfs_file.add_string_descriptor(*model_desc)
            tfs_file.add_string_descriptor(*result_desc)

            LOGGER.debug("")
            LOGGER.debug("::" + " : ".join(model_desc))
            LOGGER.debug("::" + " : ".join(result_desc))
        except KeyError as e:
            LOGGER.error("Couldn't calculate the phase advance because " + e)
            
    for i in range(len(meas.index)-1):
        
        nf = nfiles[meas.index[i+1]][meas.index[i]]
        
        tfs_file.add_table_row([
                 meas.index[i],
                 meas.index[i+1],
                 model.loc[meas.index[i], "S"],
                 model.loc[meas.index[i+1], "S"],
                 meas[meas.index[i+1]][meas.index[i]],
                 err[meas.index[i+1]][meas.index[i]],
                 mod[meas.index[i+1]][meas.index[i]],
                 model.loc[meas.index[i], plane_mu],
                 nf
                ])
    # last row = last - first
    last = len(meas.index)-1
    nf = nfiles[meas.index[0]][meas.index[last]]
    
    tfs_file.add_table_row([
        meas.index[last],
        meas.index[0],
        model.loc[meas.index[last], "S"],
        model.loc[meas.index[0], "S"],
        (meas[meas.index[0]][meas.index[last]] + plane_tune) % 1.0,
        err[meas.index[0]][meas.index[last]],
        (mod[meas.index[0]][meas.index[last]] + plane_tune) % 1.0,
        model.loc[meas.index[last], plane_mu],
        nf
    ])
    return tfs_file


def write_phasetot_file(tfs_file, plane, phase_advances, model, elements, tune_x, tune_y, accel):
    """Writes the phase advances to the first element into a file (get_phasetot_x/y.out). This replaces the calculation
    of the total phase which was done before. Now all the phase advances between all the BPMs are calculated at once
    which reduces the get_totalphase step to just reading out the correct phase advances.
    """
    
    plane_char = "X" if plane == "H" else "Y"
    plane_mu = "MU" + plane_char
    plane_tune = tune_x if plane == "H" else tune_y
    meas = phase_advances["MEAS"]
    mod = phase_advances["MODEL"]
    err = phase_advances["ERRMEAS"]
    
    tfs_file.add_float_descriptor("Q1", tune_x)
    tfs_file.add_float_descriptor("Q2", tune_y)
    tfs_file.add_column_names(["NAME", "NAME2", "S", "S1", "PHASE" + plane_char, "STDPH" + plane_char, "PH{}MDL".format(plane_char), "MU{}MDL".format(plane_char)])
    tfs_file.add_column_datatypes(["%s", "%s", "%le", "%le", "%le", "%le", "%le", "%le"])

    
    for i in range(len(meas.index)):
        tfs_file.add_table_row([
                 meas.index[i],
                 meas.index[0],
                 model.loc[meas.index[i], "S"],
                 model.loc[meas.index[0], "S"],
                 meas.loc[meas.index[0]][meas.index[i]],
                 err.loc[meas.index[0]][meas.index[i]],
                 mod.loc[meas.index[0]][meas.index[i]],
                 model.loc[meas.index[i], plane_mu]
                ])
    return tfs_file
