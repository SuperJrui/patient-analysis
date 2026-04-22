import numpy as np

def calculate_mean(data):
"""
This function computes the mean of an array
input: A one dimensional array
Output: The mean of the array

usage:
data=np.array([0,10,20,30])
mean=calculate_mean(data)
"""
	mean=np.mean(data)
	return mean 
