'''
Created on 31.05.2019

@author: pe
'''

class ContinuityError(Exception):
    '''
    classdocs
    '''
    def __init__(self, value):
        '''
        Constructor
        '''
        self.value = value
    def __str__(self):
        return repr(self.value)       