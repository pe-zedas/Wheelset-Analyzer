'''
Created on 21.05.2019

@author: pe
'''
import logging
#from toolsWheelset import *
import numpy as np
from GaussNewtonLinearReg_Exp import GaussNewtonLinearReg_ExpNorm
from ContinuityError import ContinuityError
from dates_np import (
    NAT,
    days_to_timedelta64,
    is_nat,
    timedelta64_to_days,
    to_python_datetime,
)
from datetime import datetime

_PROGNOSE_INSERT_SQL = (
    "insert into BO_RADSATZDATEN_PROGNOSE (TOPEINHEITID, TOPEINHEITBEZEICHNUNG, DGEINHEITID, "
    "DGBEZEICHNUNG, DGEINBAUPOS, RSEINHEITID, RSBEZEICHNUNG, RSEINBAUPOS, EINBAU, AUSBAU, AKTUELL, "
    "ZAEHLERARTID, ZARTBEZ, STAND, DATUM, LAUFLEISTUNG, LETZTEAENDZEIT, KM_GRENZWERT, DATUM_GRENZWERT, "
    "KM_WARNWERT, DATUM_WARNWERT) values (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10, :11, :12, :13, :14, "
    ":15, :16, :17, :18, :19, :20, :21)"
)


class VehicleAxis:
    '''
    classdocs
    '''

    def __init__(self, strVDesc, strBogie, strPosAxis, meterList1, meterList2):
        '''
        Constructor
        '''
        self.daysPerKm = 0.01
        self.topeinheitid = ""
        self.dgeinheitid = ""
        self.dgbezeichnung = ""
        self.rseinheitid = ""
        self.rsbezeichnung = ""
        self.einbau = ""
        self.ausbau = ""
        self.aktuell = ""
        self.zaehlerartid = ""
        self.zartbez = ""
        self.strDesc=strVDesc       # Fahrzeug Bezeichnung
        self.strBogie=strBogie      # Drehgestell Bezeichnung
        self.strPosAxis=strPosAxis  # Einbauposition der Achse
        self.meterList1=meterList1  # Daten Radsatz 1 Achse
        self.meterList2=meterList2  # Daten Radsatz 2 Achse

    def getstrVDesc(self):
        return self.strDesc

    def setstrVDesc(self, str_v_desc):
        self.strDesc = str_v_desc

    def getstrBogie(self):
        return self.strBogie

    def setstrBogie(self, str_bogie):
        self.strBogie = str_bogie

    def getstrPosAxis(self):
        return self.strPosAxis

    def setstrPosAxis(self, str_pos_axis):
        self.strPosAxis = str_pos_axis
    def getmeterList1(self):
        return self.meterList1
    def getmeterList2(self):
        return self.meterList2
    def getdaysPerKm(self):
        return self.daysPerKm
    def setdaysPerKm(self,dkm):
        self.daysPerKm=dkm
    def gettopeinheitid(self):
        return self.topeinheitid
    def settopeinheitid(self,topeinheitid):
        self.topeinheitid=topeinheitid
    def getdgeinheitid(self):
        return self.dgeinheitid
    def setdgeinheitid(self,dgeinheitid):
        self.dgeinheitid=dgeinheitid
    def getdgbezeichnung(self):
        return self.dgbezeichnung
    def setdgbezeichnung(self,dgbezeichnung):
        self.dgbezeichnung=dgbezeichnung
    def getrseinheitid(self):
        return self.rseinheitid
    def setrseinheitid(self,rseinheitid):
        self.rseinheitid=rseinheitid    
    def getrsbezeichnung(self):
        return self.rsbezeichnung
    def setrsbezeichnung(self,rsbezeichnung):
        self.rsbezeichnung=rsbezeichnung     
    def geteinbau(self):
        return self.einbau
    def seteinbau(self,einbau):
        self.einbau=einbau
    def getausbau(self):
        return self.ausbau
    def setausbau(self,ausbau):
        self.ausbau=ausbau 
    def getaktuell(self):
        return self.aktuell
    def setaktuell(self,aktuell):
        self.aktuell=aktuell    
    def setMeterList1Prog(self,nDatesProg,kmProg,valuesProg):
        self.meterList1.setnDatesProg(nDatesProg)
        self.meterList1.setkmProg(kmProg)
        self.meterList1.setvaluesProg(valuesProg)
    def setMeterList2Prog(self,nDatesProg,kmProg,valuesProg):
        self.meterList2.setnDatesProg(nDatesProg)
        self.meterList2.setkmProg(kmProg)
        self.meterList2.setvaluesProg(valuesProg)  
        
    def getDescBogieAxis(self):
        # gibt die Kombination aus Fahrzeug DG und Axe zurück
        return self.getstrVDesc() + ' ' + self.getstrBogie() + ' '+ self.getstrPosAxis()
              
    def eliminateJump(self,p,q,defAnst):
        qnew=np.array(q);
        p_arr = np.asarray(p)
        # p kann datetime64-Array sein → Differenz liefert timedelta64; in Tage als float umwandeln,
        # damit dy/dt die übliche Einheit mm/Tag hat (wie früher mit matlabdn-Floats).
        if np.issubdtype(p_arr.dtype, np.datetime64):
            dt = timedelta64_to_days(np.diff(p_arr))
        else:
            dt = p_arr[1:p_arr.size] - p_arr[0:p_arr.size-1]
        dy=q[1:q.size]-q[0:q.size-1];
        try:
            anst = dy / dt
        except Exception:
            logging.exception(
                "eliminateJump: Steigung dy/dt nicht berechenbar für: %s",
                self.getDescBogieAxis(),
            )
            return qnew

        nA = np.where(anst < defAnst)
        # Reprofilierungen entfernen ==> reine Verschleißkurve
        for i in range(nA[0].size,0,-1):
            indTmp=nA[0][i-1];
            yTmp=dy[indTmp];
            qnew[0:indTmp+1]=qnew[0:indTmp+1] + yTmp;            
        return qnew  
      
    def calcExpFunc1(self,px,qStart,a,nProg):
        argRange=50 
        nXValues= 20        # Bereich xWerte für Berechnung
        #q = np.array(qy)     
        yMin=qStart;     # Normierung der y-Werte auf Minimum
        #q=q-yMin;
        p = np.array(px)
        xFitRange=p[-1]-p[0]
         
        nNormValue=(nProg)/argRange # Normierug der x Werte von 1- 50 (Bereich gut für Gauss Newton Verfahren)
        if nNormValue == 0:
            nNormValue = 1
            
        p=p/nNormValue 
        p1=p[0]
        p=p-p1+1  
        
        #p=p/p1 
        xProg= (nProg-xFitRange)/nNormValue           # Normierung der x-Werte auf ersten Wert        
        pnew=np.linspace(1, (p.max() + xProg),num=nXValues) # new x scale ; num=100 (100 Werte) 
        yDataProg=a[0]-np.exp(a[1]*pnew) +yMin  # determine the approximation using P0 and r determined by Gauss-Newton method
        xDataProg=(pnew+p1-1)*nNormValue
        return xDataProg,yDataProg
    
    def findYforX(self,xy,x):
        tmpdx=xy[0,0:xy.size]-x  
        dx=np.absolute(tmpdx)    
        nMinInd=np.argmin(dx)
        if x > xy[0,nMinInd]:
            deltaXPoints=xy[0,nMinInd+1]-xy[0,nMinInd]
            deltaYPoints=xy[1,nMinInd+1]-xy[1,nMinInd]
        else:
            deltaXPoints=xy[0,nMinInd]-xy[0,nMinInd-1]
            deltaYPoints=xy[1,nMinInd]-xy[1,nMinInd-1]
        tmpx = tmpdx[nMinInd]
        y = float(xy[1, nMinInd])
        try:
            y = xy[1, nMinInd] - (tmpx / deltaXPoints) * deltaYPoints
        except Exception:
            logging.exception(
                "findYforX: Interpolation fehlgeschlagen für: %s",
                self.getDescBogieAxis(),
            )
        return y
    
    def findXforY(self,xy,y):
        tmpdy=xy[1,0:xy.size]-y  
        dy=np.absolute(tmpdy)    
        nMinInd=np.argmin(dy)
        if y < xy[1,nMinInd]:
            deltaXPoints=xy[0,nMinInd+1]-xy[0,nMinInd]
            deltaYPoints=xy[1,nMinInd+1]-xy[1,nMinInd]
        else:
            deltaXPoints=xy[0,nMinInd]-xy[0,nMinInd-1]
            deltaYPoints=xy[1,nMinInd]-xy[1,nMinInd-1]
        tmpy = tmpdy[nMinInd]
        x = float(xy[0, nMinInd])
        try:
            x = xy[0, nMinInd] - (tmpy / deltaYPoints) * deltaXPoints
        except Exception:
            logging.exception(
                "findXforY: Interpolation fehlgeschlagen für: %s",
                self.getDescBogieAxis(),
            )
        return x
    
    def insertReprofiling(self,p,q,dtStart,nValueRepro,nDays):  
        dtEnd=p[-1];            # letzter Datumswert
        dtReprofil = np.arange(dtStart,dtEnd,nDays)
          
        yNewRepro=np.array(q);
        xNewRepro=np.array(p);
    
        for i in range(1,dtReprofil.size,1):
            dtTmp=dtReprofil[i];
            nTmp=np.where(p > dtTmp);
            yNewRepro[nTmp[0]]=yNewRepro[nTmp[0]] - nValueRepro;  
        
        return xNewRepro,yNewRepro 
   
        
    def CalcPrognostic(self,nMeterList,defJumpRepro,defParamExp,nKm,nKmRepro,nValueRepro):
        try:
            if nMeterList ==1:
                nIndex=self.getmeterList1().getindexStartLastCycle() # Index >0 ==> mehrere Zyklen in den Daten
                p=np.array(self.meterList1.getnDates()[nIndex:])
                q=np.array(self.meterList1.getvalues()[nIndex:])  
                pKm=np.array(self.meterList1.getkm()[nIndex:])
            else:  
                nIndex=self.getmeterList2().getindexStartLastCycle()
                p=np.array(self.meterList2.getnDates()[nIndex:])
                q=np.array(self.meterList2.getvalues()[nIndex:])  
                pKm=np.array(self.meterList2.getkm()[nIndex:])
                
            # Test, ob p-Variable kontinuierl ansteigend ist
            dPkm=pKm[1:pKm.size]-pKm[0:pKm.size-1]
            nInd=np.where(dPkm < 0);
            #if pKm[0] > pKm[-1]:
            if nInd[0].size > 0:
                raise ContinuityError('X-Werte nicht kont ansteigend')       
                             
            # Bestimmung Anstieg Reprofilierung in Verschleißkurve + Entfernen Anstieg
            qnew=self.eliminateJump(p,q,defJumpRepro) 
           
            dtStart=pKm[-1]
            
            # Berechne eineDefault-e Funktion 
            pDefault,qDefault = self.calcExpFunc1(pKm,qnew[0],defParamExp,nKm)
        
            pqArray= np.array([pDefault.T,qDefault.T])
        
            # Default e-Funktion durch den letzen Messwert der vorhandenen Funktion gehen lassen
            yTmp=self.findYforX(pqArray,pKm[-1])
            yDelta = qnew[-1]-yTmp
            if yDelta != 0:
                qDefault=np.array(qDefault+yDelta)
                pqArray[1,:]=np.array(pqArray[1,:]+yDelta)
                
            pq=np.array([pKm.T,qnew.T])
        
            # Historischen Verlauf mit Default-Funktion zusammenführen, 
            # um daraus die Parameter für die Prognose zu ermitteln
            pqNew=np.concatenate((pqArray,pq),axis=1)
        
            # Sortieren der gemischten Werte nach den x Werten
            pqNew=pqNew[:,pqNew[0,:].argsort()]
            qnew=pqNew[1,:]
            
        
            # Neue Kurven Fit + Prognose + Kurvenparameter berechnen 
            aNew,xFitRadNew,yFitRadNew,xProgRadNew,yProgRadNew = GaussNewtonLinearReg_ExpNorm(pqNew[0,:],qnew,nKm)       
            
            # Integration der Reprofilierungen in die Prognose
            xProgRadNewRepro,yProgRadNewRepro=self.insertReprofiling(xProgRadNew,yProgRadNew,dtStart,nValueRepro,nKmRepro)
           
            yStart=self.findYforX(np.array([xProgRadNewRepro.T,yProgRadNewRepro.T]),dtStart)  # Anfangswert finden  
 
            # Löschen, Werte, die vor dem Startwert der Prognose liegen    
            nTmp=np.where(xProgRadNewRepro < dtStart);
            yProgRadNewRepro=np.delete(yProgRadNewRepro, nTmp);
            xProgRadNewRepro=np.delete(xProgRadNewRepro, nTmp);
       
            xProgRadNewRepro[0]=dtStart
            yProgRadNewRepro[0]=yStart            # Anfangswert setzen
           
           
            # Prognosefunktion soll am letzten Messwert der vorhandenen Funktion beginnen
            yTmp=self.findYforX(np.array([xProgRadNewRepro.T,yProgRadNewRepro.T]),pKm[-1])
            yDelta=yTmp - q[-1] 
            if yDelta != 0.0:
                yProgRadNewRepro=yProgRadNewRepro - yDelta

            if nMeterList == 1:
                met = self.getmeterList1()
            else:
                met = self.getmeterList2()

            # Lösche Werte im Prognosevektor oberhalb km (Min-Lage + Puffer) — Schwellen der aktuellen Zählerliste
            yTmp = self.findXforY(
                np.array([xProgRadNewRepro.T, yProgRadNewRepro.T]),
                met.getmin()[-1],
            )
            nTmp = np.where(xProgRadNewRepro > yTmp + nKmRepro)
            yProgRadNewRepro = np.delete(yProgRadNewRepro, nTmp)
            xProgRadNewRepro = np.delete(xProgRadNewRepro, nTmp)

            if nMeterList ==1:
                self.setMeterList1Prog(list(), xProgRadNewRepro.tolist(), yProgRadNewRepro.tolist())
                # Berechne Kilometer Laufleistung, wann Prognosewert Warnschwelle erreicht 
                self.getmeterList1().setgelb_min_Prog_km(self.findXforY(np.array([xProgRadNewRepro.T,yProgRadNewRepro.T]),self.getmeterList1().getgelb_min()[-1]))
                # Berechne Kilometer Laufleistung, wann Prognosewert Grenzwert erreicht 
                self.getmeterList1().setmin_Prog_km(self.findXforY(np.array([xProgRadNewRepro.T,yProgRadNewRepro.T]),self.getmeterList1().getmin()[-1]))
            else:
                self.setMeterList2Prog(list(), xProgRadNewRepro.tolist(), yProgRadNewRepro.tolist())
                # Berechne Kilometer Laufleistung, wann Prognosewert Warnschwelle erreicht 
                self.getmeterList2().setgelb_min_Prog_km(self.findXforY(np.array([xProgRadNewRepro.T,yProgRadNewRepro.T]),self.getmeterList2().getgelb_min()[-1]))
                # Berechne Kilometer Laufleistung, wann Prognosewert Grenzwert erreicht 
                self.getmeterList2().setmin_Prog_km(self.findXforY(np.array([xProgRadNewRepro.T,yProgRadNewRepro.T]),self.getmeterList2().getmin()[-1]))

        except ContinuityError as exc:
            logging.warning(
                "CalcPrognostic: Laufleistung nicht monoton steigend (%s): %s",
                self.getDescBogieAxis(),
                exc,
            )
        except Exception:
            logging.exception(
                "CalcPrognostic: unerwarteter Fehler für: %s",
                self.getDescBogieAxis(),
            )
            
    def calcDaysPerKm(self):
        try:
            nIndex = self.getmeterList1().getindexStartLastCycle()
            km_list = self.getmeterList1().getkm()
            dates_num = self.getmeterList1().getnDates()
            # dates_num kann list (leer) oder np.ndarray[datetime64[s]] sein
            n_dates = len(dates_num) if hasattr(dates_num, "__len__") else 0
            if not km_list or n_dates == 0 or nIndex >= len(km_list) or nIndex >= n_dates:
                return
            tmpKm = km_list[-1] - km_list[nIndex]
            # Differenz von datetime64 liefert timedelta64 → in Tage als float umwandeln
            delta = dates_num[-1] - dates_num[nIndex]
            nDays = float(timedelta64_to_days(delta))
            if tmpKm == 0 or nDays == 0:
                return
            if nDays / tmpKm < self.getdaysPerKm():
                self.setdaysPerKm(nDays / tmpKm)
            else:
                print('Warnung in VehicleAXis.calcDaysPerKm() für: ' + self.getDescBogieAxis() + 'Days/Km zu groß => auf Standardwert 0,01')
                logging.debug('Warnung in VehicleAXis.calcDaysPerKm() für: ' + self.getDescBogieAxis() + 'Days/Km zu groß => auf Standardwert 0,01')

        except Exception:
            logging.exception(
                "calcDaysPerKm: Fehler für: %s",
                self.getDescBogieAxis(),
            )
        
    def calcnDatesProg(self):
        dkm = self.getdaysPerKm()
        if dkm <= 0:
            return

        def _seconds_to_dt64(seconds):
            """Float-Sekunden seit Unix-Epoch → np.datetime64[s] (oder NaT)."""
            try:
                s = float(seconds)
            except (TypeError, ValueError):
                return NAT
            if not np.isfinite(s):
                return NAT
            return np.datetime64(int(round(s)), "s")

        def _process(metList):
            kmProg_raw = metList.getkmProg()
            if not kmProg_raw or len(kmProg_raw) == 0:
                return
            n_dates = metList.getnDates()
            if not hasattr(n_dates, "__len__") or len(n_dates) == 0:
                return
            last_dt = n_dates[-1]
            if is_nat(last_dt):
                return

            # Float-Sekunden-Achse für findXforY (homogene float-Arithmetik)
            last_seconds = float(np.asarray(last_dt, dtype="datetime64[s]").astype("int64"))
            kmProg_rel = np.asarray(kmProg_raw, dtype=float) - float(kmProg_raw[0])
            nDates_seconds = kmProg_rel * dkm * 86400.0 + last_seconds
            values_arr = np.asarray(metList.getvaluesProg(), dtype=float)

            # Speichern als datetime64[s]-Array
            nDatesProg_dt64 = nDates_seconds.astype("int64").astype("datetime64[s]")
            metList.setnDatesProg(nDatesProg_dt64)

            xy = np.array([nDates_seconds, values_arr])
            try:
                nX_sec_gelb = self.findXforY(xy, float(metList.getgelb_min()[-1]))
            except Exception:
                logging.exception(
                    "calcnDatesProg: gelb-Schwellen-Interpolation fehlgeschlagen für %s",
                    self.getDescBogieAxis(),
                )
                nX_sec_gelb = None
            metList.setgelb_min_Prog_dt(_seconds_to_dt64(nX_sec_gelb))

            try:
                nX_sec_min = self.findXforY(xy, float(metList.getmin()[-1]))
            except Exception:
                logging.exception(
                    "calcnDatesProg: min-Schwellen-Interpolation fehlgeschlagen für %s",
                    self.getDescBogieAxis(),
                )
                nX_sec_min = None
            metList.setmin_Prog_dt(_seconds_to_dt64(nX_sec_min))

        _process(self.getmeterList1())
        _process(self.getmeterList2())

    def _prognose_insert_tuples_for_meter(self, metList, rowV):
        """Liefert die INSERT-Tupel für eine Zählerliste (gleiche Zeilen wie write_Prog_Data)."""
        rows = []
        if metList.getvaluesProg() is None or len(metList.getvaluesProg()) == 0:
            return rows
        rowZA = [metList.getzaehlerartid(), metList.getzartbez()]
        # min_Prog_dt / gelb_min_Prog_dt: np.datetime64 (oder NaT) — NaT bedeutet "kein Wert"
        min_Prog_dt = to_python_datetime(metList.getmin_Prog_dt())
        gelb_min_Prog_dt = to_python_datetime(metList.getgelb_min_Prog_dt())
        if metList.getmin_Prog_km() and metList.getmin_Prog_km() > 0:
            min_Prog_km = metList.getmin_Prog_km()
        else:
            min_Prog_km = None
        if metList.getgelb_min_Prog_km() and metList.getgelb_min_Prog_km() > 0:
            gelb_min_Prog_km = metList.getgelb_min_Prog_km()
        else:
            gelb_min_Prog_km = None
        nDatesProg_seq = metList.getnDatesProg()
        n_dates_prog = len(nDatesProg_seq) if hasattr(nDatesProg_seq, "__len__") else 0
        for i in range(0, len(metList.getvaluesProg())):
            if n_dates_prog > 0:
                nDateProg = to_python_datetime(nDatesProg_seq[i])
            else:
                nDateProg = None
            if metList.getvaluesProg()[i] > 0:
                value_Prog_km = metList.getvaluesProg()[i]
            else:
                value_Prog_km = None
            rowProgostic = [
                value_Prog_km,
                nDateProg,
                metList.getkmProg()[i],
                datetime.now(),
                min_Prog_km,
                min_Prog_dt,
                gelb_min_Prog_km,
                gelb_min_Prog_dt,
            ]
            row = rowV + rowZA + rowProgostic
            insert_tuple = [
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9],
                row[10],
                row[11],
                row[12],
                row[13],
                row[14],
                row[15],
                row[16],
                row[17],
                row[18],
                row[19],
                row[20],
            ]
            rows.append(insert_tuple)
        return rows

    def iter_prognose_insert_tuples(self):
        """Alle Prognose-Zeilen (Meter 1, dann Meter 2) wie für BO_RADSATZDATEN_PROGNOSE."""
        rowV = [
            self.gettopeinheitid(),
            self.getstrVDesc(),
            self.getdgeinheitid(),
            self.getdgbezeichnung(),
            self.getstrBogie(),
            self.getrseinheitid(),
            self.getrsbezeichnung(),
            self.getstrPosAxis(),
            self.geteinbau(),
            self.getausbau(),
            self.getaktuell(),
        ]
        for t in self._prognose_insert_tuples_for_meter(self.getmeterList1(), rowV):
            yield t
        for t in self._prognose_insert_tuples_for_meter(self.getmeterList2(), rowV):
            yield t

    def write_Prog_Data(self, cur, con):
        print(
            "Write in DB for: "
            + self.getstrVDesc()
            + " "
            + self.getstrBogie()
            + " "
            + self.getstrPosAxis()
        )
        logging.info(
            "Write in DB for: "
            + self.getstrVDesc()
            + " "
            + self.getstrBogie()
            + " "
            + self.getstrPosAxis()
        )
        rowV = [
            self.gettopeinheitid(),
            self.getstrVDesc(),
            self.getdgeinheitid(),
            self.getdgbezeichnung(),
            self.getstrBogie(),
            self.getrseinheitid(),
            self.getrsbezeichnung(),
            self.getstrPosAxis(),
            self.geteinbau(),
            self.getausbau(),
            self.getaktuell(),
        ]
        for insert_tuple in self._prognose_insert_tuples_for_meter(
            self.getmeterList1(), rowV
        ):
            cur.execute(_PROGNOSE_INSERT_SQL, insert_tuple)
        con.commit()
        for insert_tuple in self._prognose_insert_tuples_for_meter(
            self.getmeterList2(), rowV
        ):
            cur.execute(_PROGNOSE_INSERT_SQL, insert_tuple)
        con.commit()