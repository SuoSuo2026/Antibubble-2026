import tifffile
import cv2
import numpy as np
from pathlib import Path


def read_tiff_stack(tiff_path):
    """
    读取 TIFF 文件，统一返回 shape=(N,H,W) 的灰度栈。
    """
    tiff_path = Path(tiff_path)
    if not tiff_path.exists():
        raise FileNotFoundError("TIFF 文件不存在: {}".format(tiff_path))

    data = tifffile.imread(str(tiff_path))

    if data.ndim == 2:
        stack = data[None, :, :]
    elif data.ndim == 3:
        stack = data
    elif data.ndim == 4:
        gray_frames = []
        for i in range(data.shape[0]):
            frame = data[i]
            if frame.shape[-1] == 3:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            elif frame.shape[-1] == 4:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGBA2GRAY)
            else:
                raise ValueError("无法识别的彩色帧通道数: {}".format(frame.shape))
            gray_frames.append(gray)
        stack = np.stack(gray_frames, axis=0)
    else:
        raise ValueError("不支持的 TIFF 数据维度: {}".format(data.shape))

    return stack
