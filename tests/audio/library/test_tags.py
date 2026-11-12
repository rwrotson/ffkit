from ffkit.audio.library import MergedTags, merge_tags


def test_first_merge_keeps_every_current_tag() -> None:
    merged = merge_tags(
        {"artist": "Custom"},
        new_source={"title": "Source", "artist": "Source"},
        previous_source=None,
        overrides={},
    )

    assert merged == MergedTags(
        tags={"title": "Source", "artist": "Custom"}, overrides={"artist": "Custom"}
    )


def test_repeated_merges_refresh_source_tags_and_keep_overrides() -> None:
    first = merge_tags(
        {"artist": "Artist"},
        new_source={"title": "Old", "artist": "Artist", "album": "Old album"},
        previous_source=None,
        overrides={},
    )
    assert first.tags == {"title": "Old", "artist": "Artist", "album": "Old album"}

    edited = {**first.tags, "genre": "Custom genre"}
    second = merge_tags(
        edited,
        new_source={"title": "New", "artist": "New artist", "genre": "Rock"},
        previous_source={"title": "Old", "artist": "Artist", "album": "Old album"},
        overrides=first.overrides,
    )
    assert second.tags == {"title": "New", "artist": "Artist", "genre": "Custom genre"}

    edited = {key: value for key, value in second.tags.items() if key != "artist"}
    edited["title"] = "Edited title"
    third = merge_tags(
        edited,
        new_source={"title": "Latest", "artist": "Final artist"},
        previous_source={"title": "New", "artist": "New artist", "genre": "Rock"},
        overrides=second.overrides,
    )
    assert third.tags == {
        "title": "Edited title",
        "artist": "Final artist",
        "genre": "Custom genre",
    }
