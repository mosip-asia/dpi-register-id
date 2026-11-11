# import pytest
from .works import addition, subtraction, multiplier

def test_addition():
    assert addition(10,1) == 11

def test_subtraction():
    assert subtraction(10,1) == 9

def test_multiplier():
    assert multiplier(2,6) == 12