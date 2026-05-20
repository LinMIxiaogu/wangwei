from pathlib import Path

from src.utils.storage_config import StorageConfig


def test_storage_config_creates_processing_subdirectories(tmp_path):
    config = StorageConfig(base_data_dir=str(tmp_path))

    processing_dir = config.get_video_processing_dir("travel vlog.mp4")
    audio_dir = config.get_audio_dir(processing_dir)
    keyframes_dir = config.get_keyframes_dir(processing_dir)

    assert processing_dir.exists()
    assert processing_dir.parent == tmp_path
    assert processing_dir.name.startswith("travel vlog_")
    assert audio_dir == processing_dir / "audio"
    assert keyframes_dir == processing_dir / "keyframes"
    assert audio_dir.exists()
    assert keyframes_dir.exists()


def test_storage_config_builds_audio_and_keyframe_paths(tmp_path):
    config = StorageConfig(base_data_dir=str(tmp_path))
    processing_dir = tmp_path / "case"

    audio_path = config.get_audio_file_path(processing_dir, "source.mov")
    keyframe_path = config.get_keyframe_file_path(
        processing_dir,
        frame_number=7,
        timestamp_ms=12345,
    )

    assert audio_path == processing_dir / "audio" / "source_audio.mp3"
    assert keyframe_path == processing_dir / "keyframes" / "frame_007_012345.jpg"


def test_storage_config_cleanup_processing_dir(tmp_path):
    config = StorageConfig(base_data_dir=str(tmp_path))
    processing_dir = tmp_path / "case"
    nested_file = processing_dir / "audio" / "source_audio.mp3"
    nested_file.parent.mkdir(parents=True)
    nested_file.write_text("audio")

    assert config.cleanup_processing_dir(processing_dir) is True
    assert not processing_dir.exists()


def test_storage_config_cleanup_missing_dir_is_success(tmp_path):
    config = StorageConfig(base_data_dir=str(tmp_path))

    assert config.cleanup_processing_dir(tmp_path / "missing") is True
