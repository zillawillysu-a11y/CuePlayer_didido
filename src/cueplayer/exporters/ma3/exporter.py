"""grandMA3 exporter — Sequence + Timecode XML + install Macro."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from cueplayer.exporters.common import (
    SongExportPlan,
    export_event_time_seconds,
    format_ma3_cue_no_attr,
    format_ma3_offset_seconds,
    format_ma_cue_number,
    ma3_cue_destination_handle,
    ma3_timecode_set_property_commands,
    parse_page_executor,
    sanitize_ma_name,
    timecode_span_seconds,
)
from cueplayer.exporters.xml_write import ma3_guid, write_xml

MA3_TARGET_VERSION = "2.3.2"
MA3_DATA_VERSION = "2.4.2.2"  # matches collected golden XML from this machine

# Attributes copied from a real onPC export that successfully imports.
_SEQUENCE_ATTRS = {
    "AutoStart": "Yes",
    "AutoStop": "Yes",
    "AutoFix": "No",
    "AutoStomp": "No",
    "SoftLTP": "Yes",
    "XFadeReload": "No",
    "SwapProtect": "No",
    "KillProtect": "No",
    "UseExecutorTime": "Yes",
    "OffwhenOverridden": "Yes",
    "SequMIB": "Enabled",
    "AutoPrePos": "Yes",
    "WrapAround": "Yes",
    "MasterGoMode": "None",
    "SpeedfromRate": "No",
    "Tracking": "Yes",
    "IncludeLinkLastGo": "Yes",
    "RateScale": "One",
    "SpeedScale": "One",
    "PreferCueAppearance": "No",
    "ExecutorDisplayMode": "Data and\rAppearance",
    "Action": "Pool Default",
}


def resolve_ma3_datapool_dirs(directory: Path) -> tuple[Path, Path, Path]:
    """
    Map a user-chosen folder to MA3 library datapool subfolders.

    Returns (sequences_dir, timecodes_dir, macros_dir).

    Accepts:
    - gma3_library
    - gma3_library/datapools
    - …/datapools/sequences (or timecodes / macros)
    - any other folder → creates datapools/{sequences,timecodes,macros} under it
    """
    root = Path(directory)
    name = root.name.lower()
    if name == "datapools":
        base = root
    elif name in ("sequences", "timecodes", "macros") and root.parent.name.lower() == "datapools":
        base = root.parent
    elif (root / "datapools").exists() or name == "gma3_library":
        base = root / "datapools"
    else:
        base = root / "datapools"
    return base / "sequences", base / "timecodes", base / "macros"


class Ma3Exporter:
    target_version = MA3_TARGET_VERSION
    data_version = MA3_DATA_VERSION

    def export_plan_summary(self, plan: SongExportPlan) -> dict:
        return {
            "console": "ma3",
            "target_version": self.target_version,
            "data_version": self.data_version,
            "song_name": plan.song_name,
            "export_mode": plan.profile.export_mode,
            "main_cue_count": len(plan.main_cues),
            "button_lane_count": len(plan.button_lanes),
            "button_event_count": sum(len(lane.mark_times_seconds) for lane in plan.button_lanes),
            "sequence_pool_start": plan.profile.sequence_pool_start,
            "timecode_pool": plan.profile.timecode_pool,
            "data_pool": plan.profile.data_pool,
            "main_executor": plan.profile.main_executor,
            "ltc_latency_compensation_seconds": plan.profile.ltc_latency_compensation_seconds,
        }

    def export_to_directory(
        self,
        plan: SongExportPlan,
        directory: Path,
        *,
        include_macro: bool = True,
    ) -> dict[str, Path]:
        """
        Write into MA3 datapool folders:

        - Sequence XML → datapools/sequences/
        - Timecode XML → datapools/timecodes/
        - Install Macro → datapools/macros/ (optional; show export uses one shared macro)
        """
        seq_dir, tc_dir, macro_dir = resolve_ma3_datapool_dirs(directory)
        for folder in (seq_dir, tc_dir, macro_dir):
            folder.mkdir(parents=True, exist_ok=True)

        paths: dict[str, Path] = {}

        if plan.profile.export_mode == "full":
            if plan.profile.include_main:
                paths["main_sequence"] = seq_dir / plan.profile.main_sequence_file
                self.write_main_sequence(plan, paths["main_sequence"])
            if plan.button_lanes:
                for lane in plan.button_lanes:
                    key = f"button_sequence_{lane.lane_index}"
                    path = seq_dir / (lane.sequence_file or plan.profile.button_sequence_file)
                    paths[key] = path
                    self.write_button_sequence(plan, path, sequence_name=lane.sequence_name)
                paths["button_sequence"] = paths[
                    f"button_sequence_{plan.button_lanes[0].lane_index}"
                ]
            if include_macro:
                install_base = plan.profile.main_sequence_file
                if install_base.endswith("_main.xml"):
                    install_base = install_base[: -len("_main.xml")]
                else:
                    install_base = plan.song_name or "cueplayer"
                paths["macro"] = macro_dir / f"{install_base}_install_macro.xml"
                self.write_install_macro(plan, paths["macro"])

        paths["timecode"] = tc_dir / plan.profile.timecode_file
        self.write_timecode(plan, paths["timecode"])
        return paths

    def export_show_to_directory(
        self,
        plans: list[SongExportPlan],
        directory: Path,
        *,
        show_macro_name: str = "CuePlayer_Show_Install",
    ) -> dict[str, Path]:
        """
        Export every song's Seq/TC files, plus one show-wide install Macro.
        """
        if not plans:
            return {}
        _seq_dir, _tc_dir, macro_dir = resolve_ma3_datapool_dirs(directory)
        all_paths: dict[str, Path] = {}
        for plan in plans:
            # Per-song macros skipped — one show macro at the end.
            paths = self.export_to_directory(plan, directory, include_macro=False)
            prefix = plan.song_name or "song"
            for key, path in paths.items():
                all_paths[f"{prefix}:{key}"] = path

        if any(p.profile.export_mode == "full" for p in plans):
            macro_path = macro_dir / f"{show_macro_name}.xml"
            self.write_show_install_macro(plans, macro_path, name=show_macro_name)
            all_paths["show:macro"] = macro_path
        return all_paths

    def _root(self) -> ET.Element:
        return ET.Element("GMA3", {"DataVersion": self.data_version})

    def _cue_part(self, cue_el: ET.Element) -> ET.Element:
        return ET.SubElement(
            cue_el,
            "Part",
            {
                "Guid": ma3_guid(),
                "AlignRangeX": "No",
                "AlignRangeY": "No",
                "AlignRangeZ": "No",
                "PreserveGridPositions": "No",
                "MAgic": "No",
                "Mode": "0",
                "Action": "Pool Default",
            },
        )

    def write_main_sequence(self, plan: SongExportPlan, path: Path) -> None:
        root = self._root()
        attrs = {
            "Name": plan.profile.main_sequence_name,
            "Guid": ma3_guid(),
            **_SEQUENCE_ATTRS,
        }
        sequ = ET.SubElement(root, "Sequence", attrs)
        off = ET.SubElement(
            sequ,
            "Cue",
            {
                "Name": "OffCue",
                "Release": "Yes",
                "Assert": "Assert",
                "AllowDuplicates": "",
                "TrigType": "",
            },
        )
        self._cue_part(off)
        zero = ET.SubElement(sequ, "Cue", {"Name": "CueZero", "No": "  0"})
        self._cue_part(zero)

        for cue in plan.main_cues:
            # Name before No (matches CueZero pattern) so Import keeps the label.
            attrs: dict[str, str] = {}
            label = cue.cue_name_for_export()
            if label:
                attrs["Name"] = label
            attrs["No"] = format_ma3_cue_no_attr(cue.cue_number)
            attrs["AllowDuplicates"] = ""
            cue_el = ET.SubElement(sequ, "Cue", attrs)
            part = self._cue_part(cue_el)
            part.set("Sync", "")
            part.set("Morph", "")
            # Some MA3 builds read Part name when Cue Name is dropped on import.
            if label:
                part.set("Name", label)

        write_xml(root, path)

    def write_button_sequence(
        self,
        plan: SongExportPlan,
        path: Path,
        *,
        sequence_name: str | None = None,
    ) -> None:
        root = self._root()
        attrs = {
            "Name": sequence_name or plan.profile.button_sequence_name,
            "Guid": ma3_guid(),
            **_SEQUENCE_ATTRS,
            "AutoPrePos": "No",
            "WrapAround": "No",
        }
        sequ = ET.SubElement(root, "Sequence", attrs)
        off = ET.SubElement(
            sequ,
            "Cue",
            {
                "Name": "OffCue",
                "Release": "Yes",
                "Assert": "Assert",
                "AllowDuplicates": "",
                "TrigType": "Follow",
            },
        )
        self._cue_part(off)
        zero = ET.SubElement(sequ, "Cue", {"Name": "CueZero", "No": "  0"})
        self._cue_part(zero)

        cue1 = ET.SubElement(sequ, "Cue", {"No": "  1", "AllowDuplicates": ""})
        part1 = self._cue_part(cue1)
        part1.set("Sync", "")
        part1.set("Morph", "")

        follow = f"{plan.profile.button_follow_seconds:.3f}"
        cue2 = ET.SubElement(
            sequ,
            "Cue",
            {
                "No": "  2",
                "AllowDuplicates": "",
                "TrigType": "Follow",
                "TrigTime": follow,
            },
        )
        part2 = self._cue_part(cue2)
        part2.set("Sync", "")
        part2.set("Morph", "")
        part2.set("CueInFade", "0.500")

        write_xml(root, path)

    def write_timecode(self, plan: SongExportPlan, path: Path) -> None:
        root = self._root()
        # Length covers media + tail past last cue (not just last event time).
        duration = export_event_time_seconds(timecode_span_seconds(plan), plan.profile)
        offset_text = format_ma3_offset_seconds(plan.profile.start_offset_seconds)
        # TCSlot: 1..8 = external slot (user default), -1 = none/internal.
        tc_slot = int(plan.profile.timecode_slot)
        tc_slot_attr = str(tc_slot) if tc_slot >= 0 else "-1"

        tc_attrs = {
            "Name": plan.profile.timecode_name,
            "Guid": ma3_guid(),
            "Cursor": f"{duration:.2f}",
            "Duration": f"{duration:.2f}",
            "LoopCount": "0",
            "TCSlot": tc_slot_attr,
            # Playback column (user screenshot defaults)
            "AutoStart": "Yes",
            "AutoStop": "Yes",
            "LoopMode": "Off",
            "SwitchOff": "Keep Playbacks",
            "AssertPrevEvents": "No",
            "RestartOption": "Continue",
            # Record (Playback and Record is set via install macro — UI name has spaces)
            "Goto": "as Go",
            # Display
            "TimeDisplayFormat": "10d11h23m45",
            "FrameReadout": "Seconds",
        }
        # CuePoints-style: song start LTC → OffsetTCSlot (UI: Offset TC Slot).
        tc_attrs["OffsetTCSlot"] = offset_text

        tc = ET.SubElement(
            root,
            "Timecode",
            tc_attrs,
        )
        group = ET.SubElement(tc, "TrackGroup", {"Play": "", "Rec": ""})
        ET.SubElement(group, "MarkerTrack", {"Name": "Marker", "Guid": ma3_guid()})

        pool = plan.profile.data_pool
        main_name = plan.profile.main_sequence_name
        main_target = f"ShowData.DataPools.{pool}.Sequences.{main_name}"
        main_track = ET.SubElement(
            group,
            "Track",
            {
                "Name": main_name,
                "Guid": ma3_guid(),
                "Target": main_target,
                "Play": "",
                "Rec": "",
            },
        )
        main_range = ET.SubElement(
            main_track,
            "TimeRange",
            {"Guid": ma3_guid(), "Duration": "To End", "Play": "", "Rec": ""},
        )
        main_cmds = ET.SubElement(main_range, "CmdSubTrack")
        # Numeric handles match onPC-exported golden XML (named ShowData paths
        # in Object/ValCueDestination fail to resolve Cue destinations on import).
        main_seq_idx = max(0, int(plan.profile.sequence_pool_start) - 1)
        for cue in plan.main_cues:
            cue_label = format_ma_cue_number(cue.cue_number)
            dest_handle = ma3_cue_destination_handle(cue.cue_number)
            t = export_event_time_seconds(cue.time_seconds, plan.profile)
            event = ET.SubElement(
                main_cmds,
                "CmdEvent",
                {
                    "Name": "Go+",
                    "Time": f"{t:.3f}",
                    "CueDestination": f"Cue {cue_label}",
                },
            )
            ET.SubElement(
                event,
                "RealtimeCmd",
                {
                    "Type": "Key",
                    "Source": "Original",
                    "UserProfile": "0",
                    "Environment": "0",
                    "User": "1",
                    "Status": "On",
                    "IsRealtime": "0",
                    "IsXFade": "0",
                    "IgnoreFollow": "0",
                    "IgnoreCommand": "0",
                    "Assert": "0",
                    "IgnoreNetwork": "0",
                    "FromTriggerNode": "0",
                    "IgnoreExecTime": "0",
                    "IssuedByTimecode": "0",
                    "FromLocalHardwareFader": "1",
                    "IgnoreExecXFade": "0",
                    "IsExecXFade": "0",
                    "Object": f"13.13.0.5.{main_seq_idx}",
                    "ExecToken": "Go+",
                    "ValCueDestination": f"0.5.{main_seq_idx}.{dest_handle}",
                },
            )

        if not plan.profile.include_main:
            group.remove(main_track)

        for lane_i, lane in enumerate(plan.button_lanes):
            button_name = lane.sequence_name or lane.resolved_ma_name()
            target = f"ShowData.DataPools.{pool}.Sequences.{button_name}"
            btn_pool = int(
                lane.sequence_pool
                or (plan.profile.sequence_pool_start + 1 + lane_i)
            )
            btn_seq_idx = max(0, btn_pool - 1)
            track = ET.SubElement(
                group,
                "Track",
                {
                    "Name": button_name,
                    "Guid": ma3_guid(),
                    "Target": target,
                    "Play": "",
                    "Rec": "",
                },
            )
            time_range = ET.SubElement(
                track,
                "TimeRange",
                {"Guid": ma3_guid(), "Duration": "To End", "Play": "", "Rec": ""},
            )
            cmds = ET.SubElement(time_range, "CmdSubTrack")
            for t in lane.mark_times_seconds:
                abs_t = export_event_time_seconds(t, plan.profile)
                event = ET.SubElement(
                    cmds,
                    "CmdEvent",
                    {
                        "Name": "Top",
                        "Time": f"{abs_t:.3f}",
                        "CueDestination": "Cue 1",
                    },
                )
                ET.SubElement(
                    event,
                    "RealtimeCmd",
                    {
                        "Type": "Key",
                        "Source": "Original",
                        "UserProfile": "0",
                        "Environment": "0",
                        "User": "1",
                        "Status": "On",
                        "IsRealtime": "1",
                        "IsXFade": "0",
                        "IgnoreFollow": "0",
                        "IgnoreCommand": "0",
                        "Assert": "0",
                        "IgnoreNetwork": "0",
                        "FromTriggerNode": "0",
                        "IgnoreExecTime": "0",
                        "IssuedByTimecode": "0",
                        "FromLocalHardwareFader": "1",
                        "IgnoreExecXFade": "0",
                        "IsExecXFade": "0",
                        "Object": f"13.13.0.5.{btn_seq_idx}",
                        "ExecToken": "Top",
                        "ValCueDestination": f"0.5.{btn_seq_idx}.1000",
                    },
                )

        write_xml(root, path)

    def install_commands_for_plan(self, plan: SongExportPlan) -> list[str]:
        """Command lines to install one song (Page / Seq / TC / OffsetTCSlot)."""
        main_seq = plan.profile.sequence_pool_start
        tc_pool = plan.profile.timecode_pool
        main_page, main_exec = parse_page_executor(plan.profile.main_executor)
        page_name = sanitize_ma_name(
            plan.profile.page_name or plan.song_name or "",
            fallback="",
        )

        commands: list[str] = []
        if page_name:
            commands.extend(
                [
                    f"Store Page {main_page}",
                    f'Label Page {main_page} "{page_name}"',
                ]
            )
        if plan.profile.include_main:
            commands.extend(
                [
                    f'Import Sequence {main_seq} "{plan.profile.main_sequence_file}"',
                    f'Label Sequence {main_seq} "{plan.profile.main_sequence_name}"',
                    f"Assign Sequence {main_seq} At Page {main_page}.{main_exec}",
                    f"Assign Go+ At Page {main_page}.{main_exec}",
                ]
            )
        for lane in plan.button_lanes:
            seq_pool = lane.sequence_pool or (main_seq + 1)
            seq_file = lane.sequence_file or plan.profile.button_sequence_file
            seq_name = lane.sequence_name or plan.profile.button_sequence_name
            b_page, b_exec = parse_page_executor(lane.executor)
            commands.extend(
                [
                    f'Import Sequence {seq_pool} "{seq_file}"',
                    f'Label Sequence {seq_pool} "{seq_name}"',
                    f"Assign Sequence {seq_pool} At Page {b_page}.{b_exec}",
                    f"Assign Top At Page {b_page}.{b_exec}",
                ]
            )
        commands.extend(
            [
                f'Import Timecode {tc_pool} "{plan.profile.timecode_file}"',
                f'Label Timecode {tc_pool} "{plan.profile.timecode_name}"',
            ]
        )
        commands.extend(ma3_timecode_set_property_commands(plan.profile))
        return commands

    def write_install_macro(self, plan: SongExportPlan, path: Path) -> None:
        """Per-song install Macro (still available for single-song export)."""
        self._write_macro_xml(
            path,
            name=f"CuePlayer {plan.song_name}",
            commands=self.install_commands_for_plan(plan),
        )

    def write_show_install_macro(
        self,
        plans: list[SongExportPlan],
        path: Path,
        *,
        name: str = "CuePlayer_Show_Install",
    ) -> None:
        """One Macro that installs every exported song in show order."""
        commands: list[str] = []
        for plan in plans:
            if plan.profile.export_mode != "full":
                continue
            commands.extend(self.install_commands_for_plan(plan))
        self._write_macro_xml(path, name=name, commands=commands)

    def _write_macro_xml(self, path: Path, *, name: str, commands: list[str]) -> None:
        root = self._root()
        macro = ET.SubElement(
            root,
            "Macro",
            {"Name": name, "Guid": ma3_guid()},
        )
        for i, command in enumerate(commands, start=1):
            ET.SubElement(
                macro,
                "MacroLine",
                {"Name": f"Line {i}", "Command": command, "Enabled": "Yes"},
            )
        write_xml(root, path)
