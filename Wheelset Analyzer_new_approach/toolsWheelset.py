import numpy as np


# def eliminateJump(p,q,defAnst):
#     qnew=np.array(q);
#     dt=p[1:p.size]-p[0:p.size-1];
#     dy=q[1:q.size]-q[0:q.size-1];
#     anst=dy/dt;
#     nA=np.where(anst < defAnst)
#     # Reprofilierungen entfernen ==> reine Verschleißkurve
#     for i in range(nA[0].size,0,-1):
#         indTmp=nA[0][i-1];
#         yTmp=dy[indTmp];
#         qnew[0:indTmp+1]=qnew[0:indTmp+1] + yTmp;
#         
#     return qnew   

def eliminateUnwantedCycle(p,q,diffLKD):
    qnew=np.array(q);
    pnew=np.array(p);
    dy=qnew[1:qnew.size]-qnew[0:qnew.size-1]
    nA=np.where(dy > diffLKD)
    i = nA[0].size
    if i > 0:
        indTmp=nA[0][i-1]
        qnew=np.delete(qnew, np.arange(0,indTmp+1,1))
        pnew=np.delete(pnew, np.arange(0,indTmp+1,1))    
    return pnew,qnew  
 
def getStartIndexLastCycle(p,q,diffLKD):
    qnew=np.array(q);
    pnew=np.array(p);
    dy=qnew[1:qnew.size]-qnew[0:qnew.size-1]
    nA=np.where(dy > diffLKD)
    i = nA[0].size
    if i > 0:
        indTmp=nA[0][i-1]+1
    else:
        indTmp=0
    return indTmp       
  




# def calcExpFunc(px,qy,a,nProg):
#     argRange=50 
#     dx=px[1:px.size]-px[0:px.size-1]
#     nXValues=nProg/np.mean(dx)
#     #nXValues=10                      # Bereich xWerte für Berechnung
#     q = np.array(qy)     
#     yMin=q[0];     # Normierung der y-Werte auf Minimum
#     q=q-yMin;
#     p = np.array(px)
#     xFitRange=p[-1]-p[0]
#     # Normierug der x Werte von 1- 50 
#     nNormValue=(nProg)/argRange
#     if nNormValue == 0:
#         nNormValue = 1
#         
#     p=p/nNormValue
#     
#     p1=p[0]
#     p=p-p1+1  
#     
#     #p=p/p1 
#     xProg= (nProg-xFitRange)/nNormValue           # Normierung der x-Werte auf ersten Wert
#         
#     pnew=np.linspace(1, (p.max() + xProg),num=nXValues) # new Date/Time scale ; num=100 (100 Werte) 
#     yDataProg=a[0]-np.exp(a[1]*pnew) +yMin  # determine the approximation using P0 and r determined by Gauss-Newton method
#     xDataProg=(pnew+p1-1)*nNormValue
#     return xDataProg,yDataProg






# def CalcPrognostic(p,q,pKm,defJumpRepro,defParamExp,nKm,nKmRepro,nValueRepro):
#        
# #     if nSteps > pDate1.__len__():
# #         nSteps=pDate1.__len__()
# #     pDateValues1=pDate1[0:nSteps] 
# #     pDateValues2=pDate2[0:nSteps]
# # 
# #         
# #     q1 = np.array(q1[0:nSteps]) 
# #     p1=  np.array(p1[0:nSteps]) 
# #     q2 = np.array(q2[0:nSteps]) 
# #     p2=  np.array(p2[0:nSteps])
# #     pKm1= np.array(pKm1[0:nSteps])
# #     pKm2= np.array(pKm2[0:nSteps])
#         
#     # Bestimmung Anstieg Reprofilierung in Verschleißkurve + Entfernen Anstieg
#     qnew=eliminateJump(p,q,defJumpRepro) 
#    
#     dtStart=pKm[-1]
#     
#     # Berechne eineDefault-e Funktion 
#     pDefault,qDefault = calcExpFunc1(pKm,qnew[0],defParamExp,nKm)
# 
#     pqArray= np.array([pDefault.T,qDefault.T])
# 
#     # DefaultFunktion durch den letzen Messwert der vorhandenen Funktion
#     yTmp=findYforX(pqArray,pKm[-1])
#     yDelta = qnew[-1]-yTmp
#     if yDelta != 0:
#         qDefault=np.array(qDefault+yDelta)
#         pqArray[1,:]=np.array(pqArray[1,:]+yDelta)
#         
#     pq=np.array([pKm.T,qnew.T])
# 
#     # beide Arrays verbinden
#     pqNew=np.concatenate((pqArray,pq),axis=1)
# 
#     # Sortieren nach den x Werten
#     pqNew=pqNew[:,pqNew[0,:].argsort()]
#     qnew=pqNew[1,:]
# 
#     # Neue Kurven Fit + Prognose + Kurvenparameter berechnen 
#     aNew,xFitRadNew,yFitRadNew,xProgRadNew,yProgRadNew = GaussNewtonLinearReg_ExpNorm(pqNew[0,:],qnew,nKm)       
#     
#     # Integration der Reprofilierungen in die Prognose
#     xProgRadNewRepro,yProgRadNewRepro=insertReprofiling(xProgRadNew,yProgRadNew,dtStart,nValueRepro,nKmRepro)
#    
#     # Prognosefunktion soll am letzten Messwert der vorhandenen Funktion beginnen
#     yTmp=findYforX(np.array([xProgRadNewRepro.T,yProgRadNewRepro.T]),pKm[-1])
#     yDelta=yTmp - q[-1] 
#     if yDelta != 0.0:
#         yProgRadNewRepro=yProgRadNewRepro - yDelta 
# 
# 
#     return xProgRadNewRepro,yProgRadNewRepro
    
