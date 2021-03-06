import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, os.pardir, os.pardir)))

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib import pyplot as plt, gridspec, rcParams
from utils.plotting.plot_style import MarkerList

from utils.entrypoint import EntryPointParameters, entrypoint
from utils.plotting import plot_style as ps
from utils import tfs_pandas as tfs
from utils import logging_tools


LOG = logging_tools.get_logger(__name__)


# Constants, Style and Arguments #############################################


def get_params():
    params = EntryPointParameters()
    params.add_parameter(
        flags="--files",
        help="Twiss files to plot",
        name="files",
        required=True,
        nargs="+",
        type=str,
    )
    params.add_parameter(
        flags=["-y", "--y_cols"],
        help="List of column names to plot (e.g. BETX, BETY)",
        name="y_cols",
        required=True,
        type=str,
        nargs="+",
    )
    params.add_parameter(
        flags=["-x", "--x_cols"],
        help="List of column names to use as x-values.",
        name="x_cols",
        type=str,
        nargs="+",
    )
    params.add_parameter(
        flags=["-e", "--e_cols"],
        help="List of parameters to get error values from.",
        name="e_cols",
        type=str,
        nargs="+",
    )
    params.add_parameter(
        flags="--labels",
        help="Y-Lables for the plots, default: y_col.",
        name="labels",
        type=str,
        nargs="+",
    )
    params.add_parameter(
        flags="--legends",
        help="Legends for the plots, default: filenames.",
        name="legends",
        type=str,
        nargs="+",
    )
    params.add_parameter(
        flags="--output",
        help="Base-Name of the output files. _'y_col'.pdf will be attached.",
        name="output",
        type=str,
    )
    params.add_parameter(
        flags="--changemarker",
        help="Changes marker for each line in the plot.",
        action="store_true",
        name="change_marker",
    )
    params.add_parameter(
        flags="--nolegend",
        help="Deactivates the legend.",
        action="store_true",
        name="no_legend",
    )
    params.add_parameter(
        flags="--noshow",
        help="Suppresses opening plotting windows.",
        action="store_true",
        name="no_show",
    )
    params.add_parameter(
        flags="--xy",
        help="Plots X and Y for the give parameters into one figure (two axes).",
        action="store_true",
        name="xy",
    )
    return params


IR_POS_DEFAULT = {
    "LHCB1": {
        'IP1': 23519.36962,
        'IP2': 192.923,
        'IP3': 3525.207216,
        'IP4': 6857.491433,
        'IP5': 10189.77565,
        'IP6': 13522.21223,
        'IP7': 16854.64882,
        'IP8': 20175.8654,
    },
    "LHCB2": {
        'IP1': 3195.252584,
        'IP2': 6527.5368,
        'IP3': 9859.973384,
        'IP4': 13192.40997,
        'IP5': 16524.84655,
        'IP6': 19857.13077,
        'IP7': 23189.41498,
        'IP8': 26510.4792,
    }
}

MANUAL_STYLE = {
    # differences to the standard style
    u'legend.fontsize': 16,
    u'font.weight': u'normal',
    u'axes.labelweight': u'normal',
    u'axes.grid': False,
    u'lines.markersize': 5.0,
    u'lines.linestyle': u'',
}

# Main invocation ############################################################


@entrypoint(get_params(), strict=True)
def plot(opt):
    """ Plots data from different twiss-input files into one plot.

    Keyword Args:
        Required
        files (str): Twiss files to plot
                     **Flags**: --files
        optics_params (str): List of parameters to plot upon (e.g. BETX, BETY)
                             **Flags**: --optics_params

        Optional
        change_marker: Changes marker for each line in the plot.
                       **Flags**: --changemarker
                       **Action**: ``store_true``
        error_params (str): List of parameters to get error values from.
                            **Flags**: --error_params
        labels (str): Y-Lables for the plots, default: parameters.
                      **Flags**: --labels
        legends (str): Legends for the plots, default: filenames.
                      **Flags**: --legends
        no_legend: Deactivates the legend.
                   **Flags**: --nolegend
                   **Action**: ``store_true``
        no_show: Suppresses opening plotting windows.
                 **Flags**: --noshow
                 **Action**: ``store_true``
        output (str): Base-Name of the output files. _'parameter'.pdf will be attached.
                      **Flags**: --output
        xy: Plots X and Y for the give parameters into one figure (two axes).
            **Flags**: --xy
            **Action**: ``store_true``

    """
    LOG.debug("Starting plotting of tfs files: {:s}".format(", ".join(opt.files)))

    # preparations
    opt = _check_opt(opt)
    ps.set_style("standard", MANUAL_STYLE)

    twiss_data = _get_data(opt.files)

    # plotting
    figs = _create_plots(opt.x_cols, opt.y_cols, opt.e_cols, twiss_data, opt.legends, opt.labels,
                         opt.xy, opt.change_marker, opt.no_legend)

    # exports
    if opt.output:
        _export_plots(figs, opt.output)

    if not opt.no_show:
        plt.show()

    return figs


# Private Functions ##########################################################

def _get_data(files):
    """ Load all data from files """
    return [tfs.read_tfs(f) for f in files]


def _create_plots(x_cols, y_cols, e_cols, twiss_data, legends, labels,
                  xy, change_marker, no_legend):
    """ Create plots per parameter """
    _param_map = {
        "BET": "beta",
        "BB": "betabeat",
        "D": "dispersion",
        "ND": "norm_dispersion",
        "MU": "phase",
        "X": "co",
        "Y": "co",
    }

    # create layout
    if xy:
        plane_map = {0: "X", 1: "Y"}
        gs = gridspec.GridSpec(2, 1, height_ratios=[1, 1])
    else:
        plane_map = None
        gs = gridspec.GridSpec(1, 1, height_ratios=[1])

    ir_pos = _find_ir_pos(twiss_data)

    # create individual figures
    figs = {}
    for x_col, y_col, e_col in zip(x_cols, y_cols, e_cols):
        LOG.debug("Plotting parameter '{:s}'".format(y_col))

        # create figure
        fig = plt.figure()

        p_title = y_col
        if xy:
            p_title += " X/Y"
        fig.canvas.set_window_title("Parameter '{:s}'".format(p_title))

        # plot data
        for plt_idx in range(1+xy):
            if xy:
                y_name = y_col
                y_full = y_col + plane_map[plt_idx]
                e_full = e_col + plane_map[plt_idx]

            else:
                y_name = y_col[:-1]
                y_full = y_col
                e_full = e_col

            ax = fig.add_subplot(gs[plt_idx])

            for idx, data in enumerate(twiss_data):
                x_val = data[x_col]
                y_val = data[y_full]
                try:
                    e_val = data[e_full]
                except KeyError:
                    e_val = None

                ax.errorbar(x_val, y_val, yerr=e_val,
                            fmt=get_marker(idx, change_marker),
                            label=legends[idx])

                if (idx+1) == len(twiss_data):
                    try:
                        ps.set_xLimits(data.SEQUENCE, ax)
                    except (AttributeError, ps.ArgumentError):
                        pass

            # manage layout
            if labels[plt_idx] is None:
                try:
                    # if it's a recognized column make nice label
                    ps.set_yaxis_label(_param_map[y_name], y_full[-1], ax)
                except (KeyError, ps.ArgumentError):
                    ax.set_ylabel(y_full)
            else:
                # use given label
                ax.set_ylabel(labels[plt_idx])

            if xy and plt_idx == 0:
                ax.axes.get_xaxis().set_visible(False)
                if ir_pos:
                    ps.show_ir(ir_pos, ax, mode='lines')
            else:
                ps.set_xaxis_label(ax)
                if ir_pos:
                    ps.show_ir(ir_pos, ax, mode='outside')

            if not no_legend and plt_idx == 0:
                ax.legend(loc='upper center', bbox_to_anchor=(0.5, 1.25),
                              fancybox=True, shadow=True, ncol=3)
            figs[y_col] = fig
    return figs


def _export_plots(figs, output):
    """ Export all created figures to PDF """
    for param in figs:
        pdf_path = "{:s}_{:s}.pdf".format(output, param)
        mpdf = PdfPages(pdf_path)
        fig = figs[param]
        fig.tight_layout()

        try:
            mpdf.savefig(bbox_inches='tight')
            LOG.debug("Exported GetLLM results to PDF '{:s}'".format(pdf_path))
        finally:
            mpdf.close()


# Helper #####################################################################


def _check_opt(opt):
    """ Sanity checks for the opt structure """
    if opt.legends is None:
        opt.legends = opt.files
    elif len(opt.legends) != len(opt.files):
        raise AttributeError("The number of legends and number of files differ!")

    if opt.labels is None:
        opt.labels = [None] * len(opt.y_cols)
    elif len(opt.labels) != len(opt.y_cols):
        raise AttributeError("The number of labels and number of y columns differ!")

    if opt.e_cols is None:
        opt.e_cols = [""] * len(opt.y_cols)
    elif len(opt.e_cols) != len(opt.y_cols):
        raise AttributeError("The number of error columns and number of y columns differ!")

    if opt.x_cols is None:
        opt.x_cols = ["S"] * len(opt.y_cols)
    elif len(opt.x_cols) != len(opt.y_cols):
        raise AttributeError("The number of x columns and number of y columns differ!")

    return opt


def get_marker(idx, change):
    """ Return the marker used """
    if change:
        return MarkerList.get_marker(idx)
    else:
        return rcParams['lines.marker']


def _find_ir_pos(twiss_data):
    """ Return the middle positions of the interaction regions """
    ip_names = ["IP" + str(i) for i in range(1, 9)]
    for data in twiss_data:
        try:
            ip_pos = data.loc[ip_names, 'S'].values
        except KeyError:
            try:
                # loading failed, use defaults
                return IR_POS_DEFAULT[data.SEQUENCE]
            except AttributeError:
                # continue looking
                pass
        else:
            return dict(zip(ip_names, ip_pos))

    # did not find ips or defaults
    return {}


# Script Mode ################################################################


if __name__ == "__main__":
    plot()
