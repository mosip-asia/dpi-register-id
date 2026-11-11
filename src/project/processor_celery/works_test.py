# import pytest
from .works import addition_job, subtraction_job, multiplier_job

def test_addition():
    assert addition_job(10,1) == 11

def test_subtraction():
    assert subtraction_job(10,1) == 9

def test_multiplier():
    assert multiplier_job(2,6) == 12