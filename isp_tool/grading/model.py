from dataclasses import dataclass
import copy
import numpy as np
import cv2
from scipy.ndimage import map_coordinates


@dataclass
class ColorPoint:
    source: tuple
    target: tuple
    radius: float = 25.0  # Lab distance; smooth Gaussian falloff
    strength: float = 1.0
    enabled: bool = True
    origin: str = ''  # Informational source only, never a live image reference.


class GradeHistory:
    def __init__(self):
        self.points, self.undo_stack, self.redo_stack = [], [], []

    def replace(self, points):
        if points == self.points:
            return False
        self.undo_stack.append(copy.deepcopy(self.points))
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()
        self.points = copy.deepcopy(points)
        return True

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append(copy.deepcopy(self.points))
        self.points = self.undo_stack.pop()
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append(copy.deepcopy(self.points))
        self.points = self.redo_stack.pop()
        return True


def build_lut(points, size=33):
    """RGB-indexed 3D LUT from original-colour anchors; no cumulative edits.

    Weights use Lab proximity on encoded sRGB. Weighted RGB displacements
    combine with a bounded normalizer so overlapping edits cannot explode.
    Coloured anchors fade to zero on the neutral axis; explicit grey anchors
    may edit greys. No hue-angle subtraction means the red seam is continuous.
    """
    if not 2 <= size <= 65:
        raise ValueError('LUT size must be 2…65')
    grid = np.stack(np.meshgrid(*([np.linspace(0, 1, size, dtype=np.float32)]*3), indexing='ij'), axis=-1)
    flat = grid.reshape(-1, 1, 3)
    lab = cv2.cvtColor(flat, cv2.COLOR_RGB2Lab).reshape(-1,3)
    colors = flat.reshape(-1,3)
    chroma = colors.max(axis=1)-colors.min(axis=1)
    delta = np.zeros_like(colors)
    total = np.zeros(len(colors), np.float32)
    for point in points:
        source, target = np.asarray(point.source, np.float32), np.asarray(point.target, np.float32)
        if source.shape != (3,) or target.shape != (3,) or not np.all(np.isfinite([source,target])):
            raise ValueError('Invalid RGB anchor')
        if np.any(source < 0) or np.any(source > 1) or np.any(target < 0) or np.any(target > 1):
            raise ValueError('RGB anchors must be in 0…1')
        if not 5 <= point.radius <= 100 or not 0 <= point.strength <= 1:
            raise ValueError('Invalid influence radius / strength')
        if not point.enabled or np.array_equal(source,target) or point.strength == 0:
            continue
        anchor_lab = cv2.cvtColor(source.reshape(1,1,3), cv2.COLOR_RGB2Lab).reshape(3)
        weight = np.exp(-.5*np.sum((lab-anchor_lab)**2,axis=1)/(point.radius**2))
        source_chroma = float(source.max()-source.min())
        if source_chroma > .04:
            weight *= np.clip(chroma/min(source_chroma,.15),0,1)
        delta += weight[:,None]*(target-source)*point.strength
        total += weight
    result = np.clip(colors+delta/np.maximum(total[:,None],1),0,1).reshape(grid.shape)
    result.setflags(write=False)
    return result


def apply_lut(image, lut):
    """Trilinear sampling in encoded sRGB. Alpha is handled separately."""
    src = np.clip(np.asarray(image,np.float32),0,1)
    # Interpolate displacements from Identity: an untouched LUT returns the
    # exact source, including values on an 8/16-bit rounding boundary.
    result = src.copy()
    coordinates=np.moveaxis(src*(len(lut)-1),-1,0)
    axis=np.linspace(0,1,len(lut),dtype=np.float32)
    for c in range(3):
        shape=[1,1,1];shape[c]=len(lut)
        displacement=lut[...,c]-axis.reshape(shape)
        if np.any(displacement):
            result[...,c]+=map_coordinates(displacement,coordinates,order=1,
                                           mode='nearest',prefilter=False)
    return np.clip(result,0,1)


def raster8(rgb):
    return np.rint(np.clip(rgb,0,1)*255).astype(np.uint8)


def sample_original(image,x,y,radius=2):
    x,y = int(x),int(y)
    h,w = image.shape[:2]
    if not 0 <= x < w or not 0 <= y < h:
        raise ValueError('Sample is outside image')
    return tuple(np.mean(image[max(0,y-radius):min(h,y+radius+1), max(0,x-radius):min(w,x+radius+1)],axis=(0,1)).astype(float))
