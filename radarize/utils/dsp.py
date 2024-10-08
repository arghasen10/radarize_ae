#!/usr/bin/env python3

"""Helper functions for signal processing.
"""

import numpy as np
import cv2
from numba import njit, objmode

def reshape_frame(frame, flip_ods_phase=False, flip_aop_phase=False):
    """Use this to reshape RadarFrameFull messages."""

    platform = frame.platform
    adc_output_fmt = frame.adc_output_fmt
    rx_phase_bias = np.array(
        [
            a + 1j * b
            for a, b in zip(frame.rx_phase_bias[0::2], frame.rx_phase_bias[1::2])
        ]
    )

    n_chirps = int(frame.shape[0])
    rx = np.array([int(x) for x in frame.rx])
    n_rx = int(frame.shape[1])
    tx = np.array([int(x) for x in frame.tx])
    n_tx = int(sum(frame.tx))
    n_samples = int(frame.shape[2])

    return _reshape_frame(
        np.array(frame.data),
        platform,
        adc_output_fmt,
        rx_phase_bias,
        n_chirps,
        rx,
        n_rx,
        tx,
        n_tx,
        n_samples,
        flip_ods_phase=flip_ods_phase,
        flip_aop_phase=flip_aop_phase,
    )


@njit(cache=True)
def _reshape_frame(
    data,
    platform,
    adc_output_fmt,
    rx_phase_bias,
    n_chirps,
    rx,
    n_rx,
    tx,
    n_tx,
    n_samples,
    flip_ods_phase=False,
    flip_aop_phase=False,
):
    if adc_output_fmt > 0:

        radar_cube = np.zeros(len(data) // 2, dtype=np.complex64)

        radar_cube[0::2] = 1j * data[0::4] + data[2::4]
        radar_cube[1::2] = 1j * data[1::4] + data[3::4]

        radar_cube = radar_cube.reshape((n_chirps, n_rx, n_samples))

        # Apply RX phase correction for each antenna.
        if "xWR68xx" in platform:
            if flip_ods_phase:  # Apply 180 deg phase change on RX2 and RX3
                c = 0
                for i_rx, rx_on in enumerate(rx):
                    if rx_on:
                        if i_rx == 1 or i_rx == 2:
                            radar_cube[:, c, :] *= -1
                        c += 1
            elif flip_aop_phase:  # Apply 180 deg phase change on RX1 and RX3
                c = 0
                for i_rx, rx_on in enumerate(rx):
                    if rx_on:
                        if i_rx == 0 or i_rx == 2:
                            radar_cube[:, c, :] *= -1
                        c += 1

        radar_cube = radar_cube.reshape((n_chirps // n_tx, n_rx * n_tx, n_samples))

        # Apply RX phase correction from calibration.
        c = 0
        for i_tx, tx_on in enumerate(tx):
            if tx_on:
                for i_rx, rx_on in enumerate(rx):
                    if rx_on:
                        v_rx = i_tx * len(rx) + i_rx
                        # print(v_rx)
                        radar_cube[:, c, :] *= rx_phase_bias[v_rx]
                        c += 1

    else:
        radar_cube = data.reshape((n_chirps // n_tx, n_rx * n_tx, n_samples)).astype(
            np.complex64
        )

    return radar_cube


def reshape_frame_tdm(frame, flip_ods_phase=False):
    """Use this to reshape RadarFrameFull messages."""

    platform = frame.platform
    adc_output_fmt = frame.adc_output_fmt
    rx_phase_bias = np.array(
        [
            a + 1j * b
            for a, b in zip(frame.rx_phase_bias[0::2], frame.rx_phase_bias[1::2])
        ]
    )

    n_chirps = int(frame.shape[0])
    rx = np.array([int(x) for x in frame.rx])
    n_rx = int(frame.shape[1])
    tx = np.array([int(x) for x in frame.tx])
    n_tx = int(sum(frame.tx))
    n_samples = int(frame.shape[2])

    return _reshape_frame_tdm(
        np.array(frame.data),
        platform,
        adc_output_fmt,
        rx_phase_bias,
        n_chirps,
        rx,
        n_rx,
        tx,
        n_tx,
        n_samples,
        flip_ods_phase=flip_ods_phase,
    )


@njit(cache=True)
def _tdm(radar_cube, n_tx, n_rx):
    radar_cube_tdm = np.zeros(
        (radar_cube.shape[0] * n_tx, radar_cube.shape[1], radar_cube.shape[2]),
        dtype=np.complex64,
    )

    for i in range(n_tx):
        radar_cube_tdm[i::n_tx, i * n_rx : (i + 1) * n_rx] = radar_cube[
            :, i * n_rx : (i + 1) * n_rx
        ]

    return radar_cube_tdm


@njit(cache=True)
def _reshape_frame_tdm(
    data,
    platform,
    adc_output_fmt,
    rx_phase_bias,
    n_chirps,
    rx,
    n_rx,
    tx,
    n_tx,
    n_samples,
    flip_ods_phase=False,
):

    radar_cube = _reshape_frame(
        data,
        platform,
        adc_output_fmt,
        rx_phase_bias,
        n_chirps,
        rx,
        n_rx,
        tx,
        n_tx,
        n_samples,
        flip_ods_phase,
    )

    radar_cube_tdm = _tdm(radar_cube, n_tx, n_rx)

    return radar_cube_tdm


@njit(cache=True)
def get_mean(x, axis=0):
    return np.sum(x, axis=axis) / x.shape[axis]


@njit(cache=True)
def cov_matrix(x):
    """Calculates the spatial covariance matrix (Rxx) for a given set of input data (x=inputData).
        Assumes rows denote Vrx axis.
    """

    _, num_adc_samples = x.shape
    x_T = x.T
    Rxx = x @ np.conjugate(x_T)
    Rxx = np.divide(Rxx, num_adc_samples)

    return Rxx

@njit(cache=True)
def gen_steering_vec(ang_est_range, ang_est_resolution, num_ant):
    """Generate a steering vector for AOA estimation given the theta range, theta resolution, and number of antennas
    """
    num_vec = (2 * ang_est_range + 1) / ang_est_resolution + 1
    num_vec = int(round(num_vec))
    steering_vectors = np.zeros((num_vec, num_ant), dtype="complex64")
    for kk in range(num_vec):
        for jj in range(num_ant):
            mag = (
                -1
                * np.pi
                * jj
                * np.sin((-ang_est_range - 1 + kk * ang_est_resolution) * np.pi / 180)
            )
            real = np.cos(mag)
            imag = np.sin(mag)

            steering_vectors[kk, jj] = complex(real, imag)

    return (num_vec, steering_vectors)


@njit(cache=True)
def aoa_bartlett(steering_vec, sig_in):
    """
    Perform AOA estimation using Bartlett Beamforming on a given input signal (sig_in).
    """
    n_theta = steering_vec.shape[0]
    n_rx = sig_in.shape[1]
    n_range = sig_in.shape[2]
    y = np.zeros((sig_in.shape[0], n_theta, n_range), dtype="complex64")
    for i in range(sig_in.shape[0]):
        y[i] = np.conjugate(steering_vec) @ sig_in[i]
    return y


@njit(cache=True)
def aoa_capon(x, steering_vector):
    """
    Perform AOA estimation using Capon (MVDR) Beamforming on a rx by chirp slice
    """

    Rxx = cov_matrix(x)
    Rxx_inv = np.linalg.inv(Rxx).astype(np.complex64)
    first = Rxx_inv @ steering_vector.T
    den = np.zeros(first.shape[1], dtype=np.complex64)
    steering_vector_conj = steering_vector.conj()
    first_T = first.T
    for i in range(first_T.shape[0]):
        for j in range(first_T.shape[1]):
            den[i] += steering_vector_conj[i, j] * first_T[i, j]
    den = np.reciprocal(den)

    weights = first @ den

    return den, weights


@njit(cache=True)
def compute_range_azimuth(radar_cube, angle_res=1, angle_range=90, method="apes"):

    n_range_bins = radar_cube.shape[2]
    n_rx = radar_cube.shape[1]
    n_chirps = radar_cube.shape[0]
    n_angle_bins = (angle_range * 2 + 1) // angle_res + 1

    range_cube = np.zeros_like(radar_cube)
    with objmode(range_cube="complex128[:,:,:]"):
        range_cube = np.fft.fft(radar_cube, axis=2)
    range_cube = np.transpose(range_cube, (2, 1, 0))
    range_cube = np.asarray(range_cube, dtype=np.complex64)

    range_cube_ = np.zeros(
        (range_cube.shape[0], range_cube.shape[1], range_cube.shape[2]),
        dtype=np.complex64,
    )

    _, steering_vec = gen_steering_vec(angle_range, angle_res, n_rx)

    range_azimuth = np.zeros((n_range_bins, n_angle_bins), dtype=np.complex_)
    for r_idx in range(n_range_bins):
        range_cube_[r_idx] = range_cube[r_idx]
        steering_vec_ = steering_vec
        if method == "capon":
            range_azimuth[r_idx, :], _ = aoa_capon(range_cube_[r_idx], steering_vec_)
        else:
            raise ValueError("Unknown method")

    range_azimuth = np.log(np.abs(range_azimuth))

    return range_azimuth

@njit(cache=True)
def compute_doppler_azimuth(
    radar_cube,
    angle_res=1,
    angle_range=90,
    range_initial_bin=0,
    range_subsampling_factor=2,
):

    n_chirps = radar_cube.shape[0]
    n_rx = radar_cube.shape[1]
    n_samples = radar_cube.shape[2]
    n_angle_bins = (angle_range * 2) // angle_res + 1

    # Subsample range bins.
    radar_cube_ = radar_cube[:, :, range_initial_bin::range_subsampling_factor]
    radar_cube_ -= get_mean(radar_cube_, axis=0)

    # Doppler processing.
    doppler_cube = np.zeros_like(radar_cube_)
    with objmode(doppler_cube="complex128[:,:,:]"):
        doppler_cube = np.fft.fft(radar_cube_, axis=0)
        doppler_cube = np.fft.fftshift(doppler_cube, axes=0)
    doppler_cube = np.asarray(doppler_cube, dtype=np.complex64)

    # Azimuth processing.
    _, steering_vec = gen_steering_vec(angle_range, angle_res, n_rx)

    doppler_azimuth_cube = aoa_bartlett(steering_vec, doppler_cube)
    # doppler_azimuth_cube = doppler_azimuth_cube[:,:,::5]
    doppler_azimuth_cube -= np.expand_dims(
        get_mean(doppler_azimuth_cube, axis=2), axis=2
    )

    doppler_azimuth = np.log(get_mean(np.abs(doppler_azimuth_cube) ** 2, axis=2))

    return doppler_azimuth


def normalize(data, min_val=None, max_val=None):
    """
    Normalize floats to [0.0, 1.0].
    """
    if min_val is None:
        min_val = np.min(data)
    if max_val is None:
        max_val = np.max(data)
    img = (((data - min_val) / (max_val - min_val)).clip(0.0, 1.0)).astype(data.dtype)
    return img

def preprocess_1d_radar_1843(
    radar_cube,
    angle_res=1,
    angle_range=90,
    range_subsampling_factor=2,
    min_val=10.0,
    max_val=None,
    resize_shape=(48, 48),
):
    """
    Turn radar cube into 1d doppler-azimuth heatmap.
    """

    heatmap = compute_doppler_azimuth(
        radar_cube,
        angle_res,
        angle_range,
        range_subsampling_factor=range_subsampling_factor,
    )

    heatmap = normalize(heatmap, min_val=min_val, max_val=max_val)

    heatmap = cv2.resize(heatmap, resize_shape, interpolation=cv2.INTER_AREA)

    return heatmap

