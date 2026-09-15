"""Full-resolution export work, independent of Tk and preview caches."""
import copy
from .pipeline import ISPPipeline
from .preview import export_image, export_stage_data


def export_pipeline_stage(path, image, domain, metadata, snapshot, module_id,
                          exposure_ev=0.0, roi=None, computation=False,
                          backend_preference="Auto"):
    pipeline = ISPPipeline(backend_preference=backend_preference)
    # Build only the requested prefix; downstream modules must not run.
    if module_id == "input":
        count = 0
    else:
        count = next(i+1 for i, item in enumerate(snapshot) if item["id"] == module_id)
    pipeline.modules = pipeline.modules[:count]
    stage = pipeline.process(image, domain, copy.deepcopy(metadata), snapshot=snapshot[:count])[-1]
    if computation:
        source = stage.image
        if roi is not None:
            source = source[roi.slices()]
        export_stage_data(path, source, stage.domain, metadata, stage.data_state)
    else:
        # Form the CFA mosaic before cropping so an odd ROI origin does not
        # swap Bayer phases. RGB normalization and transfer match the preview.
        if roi is not None:
            from .preview import display_rgb
            rgb = display_rgb(stage.image, stage.domain, metadata, data_state=stage.data_state)
            export_image(path, rgb[roi.slices()], "rgb", metadata, exposure_ev=exposure_ev)
        else:
            export_image(path, stage.image, stage.domain, metadata, stage.data_state, exposure_ev)
    return stage.name


def export_yuv_stage(path, source_path, metadata, module_id, exposure_ev=0, roi=None):
    from .ui.controllers.yuv_preview_controller import YUVPreviewController
    from .models import RawMetadata
    payload = YUVPreviewController.process(source_path, metadata,
        max(metadata.width, metadata.height), lambda: False)
    stage = next(s for s in payload["results"] if s.module_id == module_id)
    source = stage.image if roi is None else stage.image[roi.slices()]
    export_image(path, source, "yuv_rgb", RawMetadata(width=metadata.width, height=metadata.height),
                 exposure_ev=exposure_ev)
    return stage.name
