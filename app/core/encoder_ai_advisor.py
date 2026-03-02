from __future__ import annotations


def recommend_encoder(context: dict[str, object]) -> str | None:
    """
    Optional auto-encoder advisor hook.

    CAPTRIX loads this module dynamically when present. Keep this function
    lightweight and deterministic. You can replace this file with a more
    advanced open-source AI/ML policy implementation later.
    """
    gpu_priority = context.get("gpu_priority")
    if not isinstance(gpu_priority, list):
        return None

    support = context.get("support")
    if not isinstance(support, dict):
        return None

    fps = context.get("fps")
    try:
        fps_value = int(fps) if fps is not None else 30
    except Exception:
        fps_value = 30

    quality = str(context.get("quality_preset") or "balanced").lower()

    available = [k for k in gpu_priority if support.get(k) is True]
    if not available:
        return None

    # Heuristic policy:
    # - For 60fps capture, prefer discrete GPUs for headroom.
    if fps_value >= 60:
        for candidate in ("nvidia", "amd", "intel"):
            if candidate in available:
                return candidate

    # - For small-file profile, Intel QSV often gives efficient output.
    if quality == "small_file" and "intel" in available:
        return "intel"

    # - Otherwise follow hardware priority discovered on the host.
    return available[0]

