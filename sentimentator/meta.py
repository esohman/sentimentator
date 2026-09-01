# -*- coding: utf-8 -*-

from enum import Enum


class Status(Enum):
    OK = 0
    ERR_COARSE = 1
    ERR_FINE = 2          # retained for backwards compatibility
    ERR_WHEEL = 3
    ERR_SENTENCE = 4


class Message:
    INPUT_COARSE = 'Invalid coarse sentiment'
    INPUT_FINE = 'Invalid fine sentiment'
    INPUT_WHEEL = 'Invalid or missing wheel annotation'
    INPUT_SENTENCE = 'Invalid or missing sentence'
