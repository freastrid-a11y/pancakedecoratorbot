"""Iterative learning control for the syrup robot: learn, per design, how to adjust the
pump (or speed) so each pancake's syrup lines come out closer to the target width.

    import sys; sys.path.insert(0, "pi")
    from ilc import Learner, ILCSettings, Calibration, get_design

See pi/ilc/README.md.
"""
from .designs import Design, Stroke, get_design, BUILTIN
from .learn import ILCSettings, Learner, CorrectionStore, ilc_update, stats
from .vision import Calibration, calibrate, measure, syrup_mask, decode_image, write_png, CALIBRATION_DOTS
