'''
Created on 21.05.2019

@author: pe
'''

class MeterList():
    '''
    classdocs
    '''

    def __init__(self, strDates, nDates, km, values, nMin, nMax, gelb_min):
        '''
        Constructor
        '''
        self.kmProg = []
        self.valuesProg = []
        self.nDatesProg = []
        self.indexStartLastCycle = 0
        self.gelb_min_Prog_dt = 0
        self.gelb_min_Prog_km = 0
        self.min_Prog_dt = 0
        self.min_Prog_km = 0
        self.zaehlerartid = ""
        self.zartbez = ""
        self.strDates = strDates
        self.nDates = nDates
        self.km = km
        self.values = values
        self.max = nMax
        self.min = nMin
        self.gelb_min = gelb_min
    def getkmProg(self):
        return self.kmProg
    def setkmProg(self,km):
        self.kmProg=km
    def getvaluesProg(self):
        return self.valuesProg
    def setvaluesProg(self,values):
        self.valuesProg=values
    def getnDatesProg(self):
        return self.nDatesProg
    def setnDatesProg(self,nDates):
        self.nDatesProg=nDates
    def getkm(self):
        return self.km
    def setkm(self,km):
        self.km=km
    def getvalues(self):
        return self.values
    def setvalues(self,values):
        self.values=values
    def getnDates(self):
        return self.nDates
    def setnDates(self,nDates):
        self.nDates=nDates
    def getmin(self):
        return self.min
    def setmin(self,min):
        self.min=min
    def getmax(self):
        return self.max
    def setmax(self,max):
        self.max=max
    def getgelb_min(self):
        return self.gelb_min
    def setgelb_min(self,gelb_min):
        self.gelb_min=gelb_min
    def getstrDates(self):
        return self.strDates
    def setstrDates(self,strDates):
        self.strDates=strDates
    def getgelb_min_Prog_km(self):
        return self.gelb_min_Prog_km
    def setgelb_min_Prog_km(self,gelb_min_Prog_km):
        self.gelb_min_Prog_km=gelb_min_Prog_km  
    def getgelb_min_Prog_dt(self):
        return self.gelb_min_Prog_dt
    def setgelb_min_Prog_dt(self,gelb_min_Prog_dt):
        self.gelb_min_Prog_dt=gelb_min_Prog_dt 
    def getmin_Prog_dt(self):
        return self.min_Prog_dt
    def setmin_Prog_dt(self,min_Prog_dt):
        self.min_Prog_dt=min_Prog_dt 
    def getmin_Prog_km(self):
        return self.min_Prog_km
    def setmin_Prog_km(self,min_Prog_km):
        self.min_Prog_km=min_Prog_km 
    def getindexStartLastCycle(self):
        return self.indexStartLastCycle
    def setindexStartLastCycle(self,index):
        self.indexStartLastCycle=index
    def getzaehlerartid(self):
        return self.zaehlerartid
    def setzaehlerartid(self,zaehlerartid):
        self.zaehlerartid=zaehlerartid     
    def getzartbez(self):
        return self.zartbez
    def setzartbez(self,zartbez):
        self.zartbez=zartbez             
    
    