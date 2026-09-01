# -*- coding: utf-8 -*-

from enum import Enum


class Status(Enum):
    OK = 0
    ERR_COARSE = 1
    ERR_WHEEL = 2
    ERR_TRIAL = 3
    ERR_STUDY = 4
    ERR_SUBMISSION = 5
    ERR_DUPLICATE = 6


class Message:
    INPUT_COARSE = "Invalid coarse association"
    INPUT_WHEEL = "Invalid or missing wheel annotation"
    INPUT_TRIAL = "Invalid, stale, or out-of-order trial"
    INPUT_STUDY = "No active configured study"
    INPUT_SUBMISSION = "Invalid submission identifier"
    INPUT_DUPLICATE = "Conflicting duplicate submission"
