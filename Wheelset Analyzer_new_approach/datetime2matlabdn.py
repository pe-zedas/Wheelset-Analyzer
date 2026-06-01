import logging
from datetime import datetime, timedelta


def datetime2matlabdn(dt):
    mdn = dt + timedelta(days=366)
    frac = (dt - datetime(dt.year, dt.month, dt.day, 0, 0, 0)).seconds / (24.0 * 60.0 * 60.0)
    return mdn.toordinal() + frac


def matlabdn2datetime(matlab_datenum):
    try:
        day = datetime.fromordinal(int(matlab_datenum))
        dayfrac = timedelta(days=matlab_datenum % 1) - timedelta(days=366)
        return day + dayfrac
    except Exception:
        logging.exception(
            "matlabdn2datetime: Konvertierung fehlgeschlagen (Eingabe=%r)",
            matlab_datenum,
        )
        raise
