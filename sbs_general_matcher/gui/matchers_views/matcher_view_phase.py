import sys
from matcher_view_default import MatcherViewDefault, MatcherControllerDefault
from ..matchers_models.matcher_model_phase import MatcherModelPhase


class MatcherViewPhase(MatcherViewDefault):

    def __init__(self, controller, parent=None):
        super(MatcherViewPhase, self).__init__(controller, parent)
        self.setWindowTitle("New phase matcher")


class MatcherControllerPhase(MatcherControllerDefault):

    def _get_matcher_model(self, name, beam1_path, beam2_path, ip, use_errors, propagation):
        return MatcherModelPhase(name, beam1_path, beam2_path, ip, use_errors, propagation)

    def _get_new_name(self):
        return "ph_match"


if __name__ == "__main__":
    print >> sys.stderr, "This module is meant to be imported."
    sys.exit(-1)