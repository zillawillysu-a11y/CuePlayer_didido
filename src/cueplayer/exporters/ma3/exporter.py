"""grandMA3 exporter — Sequence + Timecode XML + install Macro."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from cueplayer.exporters.common import SongExportPlan, export_event_time_seconds, parse_page_executor
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

    def export_to_directory(self, plan: SongExportPlan, directory: Path) -> dict[str, Path]:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}

        if plan.profile.export_mode == "full":
            paths["main_sequence"] = directory / "main_sequence.xml"
            paths["button_sequence"] = directory / "button_sequence.xml"
            self.write_main_sequence(plan, paths["main_sequence"])
            self.write_button_sequence(plan, paths["button_sequence"])
            paths["macro"] = directory / "cueplayer_install_macro.xml"
            self.write_install_macro(plan, paths["macro"])

        paths["timecode"] = directory / "timecode.xml"
        self.write_timecode(plan, paths["timecode"])
        return paths

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
            cue_no = int(cue.cue_number)
            # Match golden fixture: numbered cues without Name attributes.
            cue_el = ET.SubElement(
                sequ,
                "Cue",
                {"No": f"{cue_no:3d}", "AllowDuplicates": ""},
            )
            part = self._cue_part(cue_el)
            part.set("Sync", "")
            part.set("Morph", "")

        write_xml(root, path)

    def write_button_sequence(self, plan: SongExportPlan, path: Path) -> None:
        root = self._root()
        attrs = {
            "Name": plan.profile.button_sequence_name,
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
        times = [
            export_event_time_seconds(c.time_seconds, plan.profile) for c in plan.main_cues
        ]
        for lane in plan.button_lanes:
            times.extend(
                export_event_time_seconds(t, plan.profile) for t in lane.mark_times_seconds
            )
        duration = max(times) if times else 0.0

        tc = ET.SubElement(
            root,
            "Timecode",
            {
                "Name": plan.profile.timecode_name,
                "Guid": ma3_guid(),
                "Cursor": f"{duration:.2f}",
                "Duration": f"{duration:.2f}",
                "LoopCount": "0",
                "TCSlot": "-1",
                "AutoStop": "No",
                "SwitchOff": "Keep Playbacks",
                "Goto": "as Go",
                "AssertPrevEvents": "No",
                "TimeDisplayFormat": "Default",
                "FrameReadout": "Default",
                "RestartOption": "Continue",
            },
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
        for cue in plan.main_cues:
            cue_no = int(cue.cue_number)
            t = export_event_time_seconds(cue.time_seconds, plan.profile)
            event = ET.SubElement(
                main_cmds,
                "CmdEvent",
                {
                    "Name": "Go+",
                    "Time": f"{t:.3f}",
                    "CueDestination": f"Cue {cue_no}",
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
                    "Object": "13.13.0.5.0",
                    "ExecToken": "Go+",
                    "ValCueDestination": f"0.5.0.{cue_no}000",
                },
            )

        for lane_i, lane in enumerate(plan.button_lanes):
            button_name = (
                plan.profile.button_sequence_name if lane_i == 0 else lane.resolved_ma_name()
            )
            target = f"ShowData.DataPools.{pool}.Sequences.{button_name}"
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
                        "Object": "13.13.0.5.1",
                        "ExecToken": "Top",
                        "ValCueDestination": "0.5.1.1000",
                    },
                )

        write_xml(root, path)

    def write_install_macro(self, plan: SongExportPlan, path: Path) -> None:
        """
        CuePoints-style install Macro:
        import sequences, assign to executors, set keys, import timecode.
        """
        root = self._root()
        macro = ET.SubElement(
            root,
            "Macro",
            {"Name": "CuePlayer Export", "Guid": ma3_guid()},
        )

        main_seq = plan.profile.sequence_pool_start
        button_seq = plan.profile.sequence_pool_start + 1
        tc_pool = plan.profile.timecode_pool
        main_page, main_exec = parse_page_executor(plan.profile.main_executor)
        button_page, button_exec = parse_page_executor(
            plan.button_lanes[0].executor if plan.button_lanes else "1.201"
        )

        commands = [
            f'Import Sequence {main_seq} "{plan.profile.main_sequence_file}"',
            f'Label Sequence {main_seq} "{plan.profile.main_sequence_name}"',
            f"Assign Sequence {main_seq} At Page {main_page}.{main_exec}",
            # Official MA3 syntax: Assign [Function] At Page x.y
            f"Assign Go+ At Page {main_page}.{main_exec}",
            f'Import Sequence {button_seq} "{plan.profile.button_sequence_file}"',
            f'Label Sequence {button_seq} "{plan.profile.button_sequence_name}"',
            f"Assign Sequence {button_seq} At Page {button_page}.{button_exec}",
            f"Assign Top At Page {button_page}.{button_exec}",
            f'Import Timecode {tc_pool} "{plan.profile.timecode_file}"',
            f'Label Timecode {tc_pool} "{plan.profile.timecode_name}"',
        ]
        for i, command in enumerate(commands, start=1):
            ET.SubElement(
                macro,
                "MacroLine",
                {"Name": f"Line {i}", "Command": command, "Enabled": "Yes"},
            )

        write_xml(root, path)
