from .math_module import xp, _scipy, ensure_np_array
import numpy as np
import scipy

import poppy

import astropy.units as u
from astropy.io import fits
import pickle

def pad_or_crop( arr_in, npix ):
    n_arr_in = arr_in.shape[0]
    if n_arr_in == npix:
        return arr_in
    elif npix < n_arr_in:
        x1 = n_arr_in // 2 - npix // 2
        x2 = x1 + npix
        arr_out = arr_in[x1:x2,x1:x2].copy()
    else:
        arr_out = xp.zeros((npix,npix), dtype=arr_in.dtype)
        x1 = npix // 2 - n_arr_in // 2
        x2 = x1 + n_arr_in
        arr_out[x1:x2,x1:x2] = arr_in
    return arr_out

def rotate_arr(arr, rotation, reshape=False, order=3):
    if arr.dtype == complex:
        arr_r = _scipy.ndimage.rotate(xp.real(arr), angle=rotation, reshape=reshape, order=order)
        arr_i = _scipy.ndimage.rotate(xp.imag(arr), angle=rotation, reshape=reshape, order=order)
        
        rotated_arr = arr_r + 1j*arr_i
    else:
        rotated_arr = _scipy.ndimage.rotate(arr, angle=rotation, reshape=reshape, order=order)
    return rotated_arr

def interp_arr(arr, pixelscale, new_pixelscale, order=3):
        Nold = arr.shape[0]
        old_xmax = pixelscale * Nold/2

        x,y = xp.ogrid[-old_xmax:old_xmax-pixelscale:Nold*1j,
                       -old_xmax:old_xmax-pixelscale:Nold*1j]

        Nnew = int(np.ceil(2*old_xmax/new_pixelscale)) - 1
        new_xmax = new_pixelscale * Nnew/2

        newx,newy = xp.mgrid[-new_xmax:new_xmax-new_pixelscale:Nnew*1j,
                             -new_xmax:new_xmax-new_pixelscale:Nnew*1j]

        x0 = x[0,0]
        y0 = y[0,0]
        dx = x[1,0] - x0
        dy = y[0,1] - y0

        ivals = (newx - x0)/dx
        jvals = (newy - y0)/dy

        coords = xp.array([ivals, jvals])

        interped_arr = _scipy.ndimage.map_coordinates(arr, coords, order=order)
        return interped_arr


def lstsq(modes, data):
    """Least-Squares fit of modes to data.

    Parameters
    ----------
    modes : iterable
        modes to fit; sequence of ndarray of shape (m, n)
    data : numpy.ndarray
        data to fit, of shape (m, n)
        place NaN values in data for points to ignore

    Returns
    -------
    numpy.ndarray
        fit coefficients

    """
    mask = xp.isfinite(data)
    data = data[mask]
    modes = xp.asarray(modes)
    modes = modes.reshape((modes.shape[0], -1))  # flatten second dim
    modes = modes[:, mask.ravel()].T  # transpose moves modes to columns, as needed for least squares fit
    c, *_ = xp.linalg.lstsq(modes, data, rcond=None)
    return c

def generate_wfe(diam, 
                 opd_index=2.5, amp_index=2, 
                 opd_seed=1234, amp_seed=12345,
                 opd_rms=10*u.nm, amp_rms=0.05,
                 npix=256, oversample=4, 
                 wavelength=500*u.nm):
    amp_rms *= u.nm
    wf = poppy.FresnelWavefront(beam_radius=diam/2, npix=npix, oversample=oversample, wavelength=wavelength)
    wfe_opd = poppy.StatisticalPSDWFE(index=opd_index, wfe=opd_rms, radius=diam/2, seed=opd_seed).get_opd(wf)
    wfe_amp = poppy.StatisticalPSDWFE(index=amp_index, wfe=amp_rms, radius=diam/2, seed=amp_seed).get_opd(wf)
    # print(wfe_amp)
    wfe_amp /= amp_rms.unit.to(u.m)
    
    wfe_amp = xp.asarray(ensure_np_array(wfe_amp))
    wfe_opd = xp.asarray(ensure_np_array(wfe_opd))

    mask = ensure_np_array(poppy.CircularAperture(radius=diam/2).get_transmission(wf))>0
    Zs = ensure_np_array(poppy.zernike.arbitrary_basis(mask, nterms=3, outside=0))
    
    Zc_amp = lstsq(Zs, wfe_amp)
    Zc_opd = lstsq(Zs, wfe_opd)
    for i in range(3):
        wfe_amp -= Zc_amp[i] * Zs[i]
        wfe_opd -= Zc_opd[i] * Zs[i]
    wfe_amp += 1

    wfe = wfe_amp * jnp.exp(1j*2*np.pi/wavelength.to_value(u.m) * wfe_opd)
    wfe *= jnp.asarray(ensure_np_array(poppy.CircularAperture(radius=diam/2).get_transmission(wf)))
    
    return wfe

def save_fits(fpath, data, header=None, ow=True, quiet=False):
    if header is not None:
        keys = list(header.keys())
        hdr = fits.Header()
        for i in range(len(header)):
            hdr[keys[i]] = header[keys[i]]
    else: 
        hdr = None
    
    data = ensure_np_array(data)
    
    hdu = fits.PrimaryHDU(data=data, header=hdr)
    hdu.writeto(str(fpath), overwrite=ow) 
    if not quiet: print('Saved data to: ', str(fpath))

# functions for saving python objects
def save_pickle(fpath, data, quiet=False):
    out = open(str(fpath), 'wb')
    pickle.dump(data, out)
    out.close()
    if not quiet: print('Saved data to: ', str(fpath))

def load_pickle(fpath):
    infile = open(str(fpath),'rb')
    pkl_data = pickle.load(infile)
    infile.close()
    return pkl_data

def centroid(arr, rounded=False):
    weighted_sum_x = 0
    total_sum_x = 0
    for i in range(arr.shape[1]):
        weighted_sum_x += np.sum(arr[:,i])*i
        total_sum_x += np.sum(arr[:,i])
    xc = round(weighted_sum_x/total_sum_x) if rounded else weighted_sum_x/total_sum_x
    
    weighted_sum_y = 0
    total_sum_y = 0
    for i in range(arr.shape[0]):
        weighted_sum_y += np.sum(arr[i,:])*i
        total_sum_y += np.sum(arr[i,:])
        
    yc = round(weighted_sum_y/total_sum_y) if rounded else weighted_sum_y/total_sum_y
    return (yc, xc)


import socket

def send(data, host, port):
    # # Create a 5x10 NumPy array for demonstration
    # data = np.random.rand(5, 10)

    # Create a socket and connect to the receiver
    # host = '18.18.33.51'
    # port = 12345
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))

    # Serialize the NumPy array as a binary string
    data_bytes = data.tobytes()

    # Send the data to the receiver
    s.send(data_bytes)

    # Close the socket
    s.close()
    
    