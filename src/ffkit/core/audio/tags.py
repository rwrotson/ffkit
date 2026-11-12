from collections.abc import Mapping

from ffkit.core.audio.models import MergedTags


def merge_tags(
    tags: Mapping[str, str],
    *,
    new_source: Mapping[str, str],
    previous_source: Mapping[str, str] | None,
    overrides: Mapping[str, str],
) -> MergedTags:
    """Replace source tags with newly probed ones and keep tags the caller changed.

    Without ``previous_source`` every current tag is treated as an override. Otherwise a tag is an
    override when it is listed in ``overrides`` or differs from ``previous_source``.
    """
    if previous_source is None:
        kept = dict(tags)
    else:
        kept = {key: value for key, value in tags.items() if key in overrides}
        kept.update(
            (key, value)
            for key, value in tags.items()
            if key not in overrides and previous_source.get(key) != value
        )

    return MergedTags(tags={**new_source, **kept}, overrides=kept)
