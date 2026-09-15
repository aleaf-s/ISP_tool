"""sRGB-encoded colour documents; never routed through RAW normalization."""
from dataclasses import dataclass, field
from pathlib import Path
import io
import numpy as np
import cv2
from PIL import Image, ImageCms, ImageOps
import tifffile
from .model import apply_lut, raster8


@dataclass
class ColorDocument:
    path: str
    rgb: np.ndarray
    alpha: object
    bit_depth: int
    note: str
    view_state: dict = field(default_factory=dict)


def read_color_image(path):
    if Path(path).suffix.lower() not in ('.png','.jpg','.jpeg','.tif','.tiff'):
        raise ValueError('Only PNG / JPEG / TIFF are supported')
    with Image.open(path) as picture:
        icc = picture.info.get('icc_profile')
        orientation = picture.getexif().get(274,1)
        # Decode high bit depth without Pillow's RGB uint8 conversion.
        raw = cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_UNCHANGED)
        if raw is None:
            raise ValueError('Cannot decode image')
        if raw.dtype == np.uint16:
            if icc:
                raise ValueError('16-bit ICC conversion is not supported yet; convert to untagged sRGB 16-bit or tagged 8-bit first. No precision was discarded.')
            if raw.ndim != 3 or raw.shape[2] not in (3,4):
                raise ValueError('A colour RGB/RGBA image is required')
            rgb = raw[...,[2,1,0]].astype(np.float32)/65535
            alpha = raw[...,3].astype(np.float32)/65535 if raw.shape[2] == 4 else None
            operations = {2:lambda a:np.fliplr(a),3:lambda a:np.rot90(a,2),4:lambda a:np.flipud(a),
                          5:lambda a:np.swapaxes(a,0,1),6:lambda a:np.rot90(a,-1),
                          7:lambda a:np.flip(np.swapaxes(a,0,1),(0,1)),8:lambda a:np.rot90(a)}
            if orientation in operations:
                rgb=operations[orientation](rgb)
                if alpha is not None:
                    alpha=operations[orientation](alpha)
            depth,note=16,'No ICC · assumed sRGB (16-bit)'
        elif raw.dtype == np.uint8:
            picture = ImageOps.exif_transpose(picture)
            alpha = np.asarray(picture.convert('RGBA'))[...,3].astype(np.float32)/255 if 'A' in picture.getbands() or 'transparency' in picture.info else None
            if icc:
                profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                # Keep CMYK when its embedded ICC expects CMYK input.
                source = picture if picture.mode in ('RGB','CMYK','LAB','L') else picture.convert('RGB')
                picture = ImageCms.profileToProfile(source,profile,ImageCms.createProfile('sRGB'),outputMode='RGB')
                note='ICC → sRGB'
            else:
                if picture.mode == 'CMYK':
                    raise ValueError('CMYK input requires an ICC profile')
                picture=picture.convert('RGB')
                note='No ICC · assumed sRGB'
            rgb=np.asarray(picture,dtype=np.float32)/255
            depth=8
        else:
            raise ValueError('Only 8/16-bit integer colour images are supported; no HDR/Log conversion')
    rgb=np.ascontiguousarray(rgb)
    rgb.setflags(write=False)
    return ColorDocument(str(path),rgb,alpha,depth,note)


def export_color_image(path,document,lut):
    output=np.empty_like(document.rgb)
    for y in range(0,len(output),128):
        output[y:y+128]=apply_lut(document.rgb[y:y+128],lut)
    if document.alpha is not None:
        output=np.dstack((output,document.alpha))
    icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    if Path(path).suffix.lower() in ('.tif','.tiff'):
        tifffile.imwrite(path,np.rint(output*65535).astype(np.uint16),photometric='rgb',
                          extratags=[(34675,'B',len(icc),icc,False)],
                          **({'extrasamples':['unassalpha']} if document.alpha is not None else {}))
    else:
        if Path(path).suffix.lower() != '.png':
            raise ValueError('Export supports PNG or TIFF')
        Image.fromarray(raster8(output)).save(path,icc_profile=icc)
