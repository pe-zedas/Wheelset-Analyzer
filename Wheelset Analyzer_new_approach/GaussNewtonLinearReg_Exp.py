import math
import numpy as np
import matplotlib.pyplot as plt

def df(p,q,a1,a2,index):             # calculate partial derivatives; Formel P(t)=a1-2^(a2*t); p=t=x; q=P(t)=y
    if index==0:
        value = 1                    # 1. Ableitung nach a1
    if index==1:
        value = -p*math.exp(a2*p)    # 1. Ableitung nach a2
    return value
    # end function df
    
def GaussNewtonLinearReg_Exp(px,qy,nDays):
    # GaussNewtonPopulation - Uses the Gauss-Newton Method (Gauss-Newton Approximation) to find the initial
    tol = 1e-8                            # set a value for the accuracy
    maxstep = 30                          # set maximum number of steps to run for
    
    q = np.array(qy)     
    #yMin=q.min();     # Normierung der y-Werte auf Minimum
    yMin=q[0]
    q=q-yMin;
    p = np.array(px)
    p1=p[0]
    p=p-p1+1                # Normierung der x-Werte auf ersten Wert
    pnew=np.linspace(1, (p.max() + nDays),num=200) # new Date/Time scale ; num=100 (100 Werte) 
    
    
    a = [10,0.01]           # Initial Values

    m=p.size                #determine number of functions
    n=len(a)                #determine number of unknowns
    aold = a;
    J = np.array([[0]*n]*m,dtype=np.float64)
    JT = np.array([[0]*m]*n,dtype=np.float64)
    r = np.array([0]*m,dtype=np.float64)
    
    ######################################################################
    for k in range(1,maxstep): #iterate through process
        S = 0;
        for i in range(0,m):
            for j in range(0,n):
                J[i][j] = df(p[i],q[i],a[0],a[1],j)    # calculate Jacobian
                JT[j][i] = J[i][j]                     # and its transpose
            # end for
        # end for
        Jz = -JT.dot(J)     # multiply Jacobian and negative transpose
        
        for i in range(0,m):
            r[i] = q[i] - (a[0]-math.exp(p[i]*a[1]))    # calculate r; Formel P(t)=a1-(e)^(t*a2); p=t=x; q=P(t)=y
            S = S + r[i]**2                             # calculate the sum of the squares of the residuals
            # end for
    
        InvJz=np.linalg.inv(Jz)
        g=InvJz.dot(JT)                 # mulitply Jz inverse by J transpose
        a = aold-g.dot(r)        # calculate new approximation
        #     %a = aold-(inv(JT*J)*JT)*r;
        unknowns = a                # set w equal to most recent approximations of the unkowns
        e= abs(a[0]-aold[0])    # calculate error
        if (e <= tol):   # if less than tolerance break
            break
            #  end
        aold = a   #set aold to a
        # end for
    ##########################################################################
    
    times = np.linspace(p[0],p[-1])                 # new Date/Time scale ; num=50 -> default (50 Werte)
    yFit=unknowns[0]-np.exp(unknowns[1]*times) +yMin;      # determine the approximation using P0 and r determined by Gauss-Newton method
    yDataProg=unknowns[0]-np.exp(unknowns[1]*pnew) +yMin;  # determine the approximation using P0 and r determined by Gauss-Newton method
    xFit=times+p1-1;
    xDataProg=pnew+p1-1;
    return a,xFit,yFit,xDataProg,yDataProg;
    
    
def GaussNewtonLinearReg_ExpNorm(px,qy,nProg):
    # GaussNewtonPopulation - Uses the Gauss-Newton Method (Gauss-Newton Approximation) to find the initial
    tol = 1e-8                            # set a value for the accuracy
    maxstep = 30                          # set maximum number of steps to run for
    argRange=50                        # Bereich xWerte für Berechnung
    q = np.array(qy)     
    yMin=q[0];     # Normierung der y-Werte auf Minimum
    q=q-yMin;
    p = np.array(px)
    xFitRange=p[-1]-p[0]
   
    # Normierug der x Werte von 1- 50 
    nNormValue=(nProg)/argRange
    if nNormValue == 0:
        nNormValue = 1
        
    p=p/nNormValue
    
    p1=p[0]
    p=p-p1+1  
    
    #p=p/p1 
    xProg= (nProg-xFitRange)/nNormValue           # Normierung der x-Werte auf ersten Wert
    
    
    a = [10,0.01]           # Initial Values
    a = [10,0.03]
    m=p.size                #determine number of functions
    n=len(a)                #determine number of unknowns
    aold = a;
    J = np.array([[0]*n]*m,dtype=np.float64)
    JT = np.array([[0]*m]*n,dtype=np.float64)
    r = np.array([0]*m,dtype=np.float64)
    
    ######################################################################
    for k in range(1,maxstep): #iterate through process
        S = 0;
        for i in range(0,m):
            for j in range(0,n):
                J[i][j] = df(p[i],q[i],a[0],a[1],j)    # calculate Jacobian
                JT[j][i] = J[i][j]                     # and its transpose
            # end for
        # end for
        Jz = -JT.dot(J)     # multiply Jacobian and negative transpose
        
        for i in range(0,m):
            r[i] = q[i] - (a[0]-math.exp(p[i]*a[1]))    # calculate r; Formel P(t)=a1-(e)^(t*a2); p=t=x; q=P(t)=y
            S = S + r[i]**2                             # calculate the sum of the squares of the residuals
            # end for
    
        InvJz=np.linalg.inv(Jz)
        g=InvJz.dot(JT)                 # mulitply Jz inverse by J transpose
        a = aold-g.dot(r)        # calculate new approximation
        #     %a = aold-(inv(JT*J)*JT)*r;
        unknowns = a                # set w equal to most recent approximations of the unkowns
        e= abs(a[0]-aold[0])    # calculate error
        if (e <= tol):   # if less than tolerance break
            break
            #  end
        aold = a   #set aold to a
        # end for
    ##########################################################################
#     p=p+p1-1
#     p=p*30000
    times = np.linspace(p[0],p[-1])                 # new Date/Time scale ; num=50 -> default (50 Werte)
    yFit=unknowns[0]-np.exp(unknowns[1]*times) +yMin; 
    pnew=np.linspace(1, (p.max() + xProg),num=200) # new Date/Time scale ; num=100 (100 Werte) 
    # determine the approximation using P0 and r determined by Gauss-Newton method
    yDataProg=unknowns[0]-np.exp(unknowns[1]*pnew) +yMin;  # determine the approximation using P0 and r determined by Gauss-Newton method
#     plt.figure(figsize=(20,8), dpi=80)
#     plt.plot(pnew,yDataProg)
#     plt.plot(times,yFit)
    #xFit=(times-1)*nNormValue;
    xFit=(times+p1-1)*nNormValue
    xDataProg=(pnew+p1-1)*nNormValue;
    return a,xFit,yFit,xDataProg,yDataProg;
