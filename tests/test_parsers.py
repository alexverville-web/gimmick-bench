"""Parser tests. The sample outputs below are hand-written to match each tool's
documented format; they are not captured from a studio machine."""
import unittest

from gimmick_bench.apps.aftereffects import parse_render_timing
from gimmick_bench.apps.cinema4d import parse_commandline_timing
from gimmick_bench.platform import macos, windows
from gimmick_bench.proc import TimedLine


def lines(pairs):
    return [TimedLine(t, s) for t, s in pairs]


class AerenderTimingTest(unittest.TestCase):
    def test_start_finish_lines(self):
        out = lines([
            (8.0, "PROGRESS:  Launching After Effects..."),
            (14.0, "PROGRESS:  10/26/2026 6:00:00 PM: Starting composition “BENCH_shapes”."),
            (15.0, "PROGRESS:  0;00;00;00 (1): 1 Seconds"),
            (16.0, "PROGRESS:  0;00;00;01 (2): 1 Seconds"),
            (17.0, "PROGRESS:  0;00;00;02 (3): 1 Seconds"),
            (17.2, "PROGRESS:  10/26/2026 6:00:03 PM: Finished composition “BENCH_shapes”."),
        ])
        r = parse_render_timing(out, 3)
        self.assertEqual(r["method"], "start_finish_lines")
        self.assertAlmostEqual(r["render_s"], 3.2)
        self.assertEqual(r["frames_seen"], 3)
        self.assertNotIn("frames_missing", r)

    def test_frame_lines_fallback_for_other_languages(self):
        out = lines([(10.0 + i, f"PROGRESS:  {i:05d} ({i + 1}): 1 Secondes") for i in range(5)])
        r = parse_render_timing(out, 5)
        self.assertEqual(r["method"], "frame_lines")
        self.assertAlmostEqual(r["render_s"], 4.0 * 5 / 4)

    def test_wall_time_last_resort_and_missing_frames(self):
        r = parse_render_timing(lines([(1.0, "PROGRESS:  0;00;00;00 (1): 0 Seconds")]), 10)
        self.assertEqual(r["method"], "wall_time")
        self.assertIsNone(r["render_s"])
        self.assertEqual(r["frames_missing"], 9)

    def test_errors_collected(self):
        r = parse_render_timing(lines([(1.0, "aerender ERROR: No comp was found with the given name.")]))
        self.assertEqual(len(r["errors"]), 1)


class CommandlineTimingTest(unittest.TestCase):
    def test_success_line(self):
        r = parse_commandline_timing(lines([
            (20.0, "Rendering frame 0 at 'Mon Oct 26 18:00:00 2026'"),
            (30.0, "Rendering frame 1 at 'Mon Oct 26 18:00:10 2026'"),
            (40.0, "Rendering successful: 19.873 sec."),
        ]))
        self.assertEqual(r["method"], "rendering_successful_line")
        self.assertAlmostEqual(r["render_s"], 19.873)

    def test_frame_fallback(self):
        r = parse_commandline_timing(lines([
            (20.0, "Rendering frame 0"), (30.0, "Rendering frame 1"), (41.0, "done"),
        ]))
        self.assertEqual(r["method"], "frame_lines")
        self.assertAlmostEqual(r["render_s"], 21.0)


SP_APPLE_SILICON = {
    "SPHardwareDataType": [{
        "_name": "hardware_overview", "chip_type": "Apple M2 Max", "machine_model": "Mac14,13",
        "machine_name": "Mac Studio", "number_processors": "proc 12:8:4", "physical_memory": "32 GB",
    }],
    "SPDisplaysDataType": [{"_name": "Apple M2 Max", "sppci_model": "Apple M2 Max", "sppci_cores": "30",
                            "spdisplays_vendor": "sppci_vendor_Apple"}],
    "SPStorageDataType": [{
        "_name": "Macintosh HD", "mount_point": "/", "size_in_bytes": 994662584320,
        "free_space_in_bytes": 412316860416,
        "physical_drive": {"medium_type": "ssd", "protocol": "Apple Fabric"},
    }],
    "SPSoftwareDataType": [{"os_version": "macOS 15.6 (24G84)"}],
    "SPMemoryDataType": [{"SPMemoryDataType": "32 GB", "dimm_type": "LPDDR5"}],
}

SP_INTEL_IMAC = {
    "SPHardwareDataType": [{"cpu_type": "8-Core Intel Core i9", "machine_model": "iMac20,1",
                            "machine_name": "iMac", "physical_memory": "64 GB"}],
    "SPDisplaysDataType": [{"sppci_model": "AMD Radeon Pro 5700 XT", "spdisplays_vram": "16 GB"}],
    "SPMemoryDataType": [{"_items": [
        {"_name": "DIMM0", "dimm_size": "16 GB"}, {"_name": "DIMM1", "dimm_size": "16 GB"},
        {"_name": "DIMM2", "dimm_size": "16 GB"}, {"_name": "DIMM3", "dimm_size": "16 GB"}]}],
}


class MacParseTest(unittest.TestCase):
    def test_apple_silicon(self):
        p = macos.parse_system_profiler(SP_APPLE_SILICON)
        self.assertEqual(p["model_id"], "Mac14,13")
        self.assertEqual((p["cpu_cores"], p["p_cores"], p["e_cores"]), (12, 8, 4))
        self.assertEqual(p["ram_gb"], 32)
        self.assertEqual(p["gpus"][0].cores, 30)
        self.assertIsNone(p["gpus"][0].vram_gb)
        self.assertEqual(p["disks"][0].medium, "SSD")
        self.assertTrue(p["disks"][0].is_boot)
        self.assertNotIn("ram_slots_total", p)

    def test_intel_imac_slots_and_vram(self):
        p = macos.parse_system_profiler(SP_INTEL_IMAC)
        self.assertEqual(p["gpus"][0].vram_gb, 16)
        self.assertEqual(p["ram_slots_total"], 4)
        self.assertEqual(p["ram_slots_used"], 4)

    def test_small_parsers(self):
        self.assertAlmostEqual(macos.parse_swapusage("total = 2048.00M  used = 1024.00M  free = 1024.00M  (encrypted)"), 1.0)
        vm = "Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages occupied by compressor:   65536.\n"
        self.assertAlmostEqual(macos.parse_vm_stat_compressed(vm), 1.0)
        self.assertEqual(macos.parse_pmset_therm("CPU_Scheduler_Limit = 100\nCPU_Speed_Limit = 72\n"), 72)
        self.assertEqual(macos.parse_size_gb("1.5 TB"), 1536)

    def test_model_table(self):
        from gimmick_bench.platform import mac_models
        self.assertEqual(mac_models.lookup("iMac20,1")[1], 2020)
        self.assertTrue(mac_models.lookup("MacPro7,1")[2])
        self.assertEqual(mac_models.year_from_marketing_name("MacBook Pro (14-inch, 2023)"), 2023)


CIM_WORKSTATION = {
    "cs": {"Name": "WS07", "Manufacturer": "Dell Inc.", "Model": "Precision 5860 Tower",
           "TotalPhysicalMemory": 68719476736, "PCSystemType": 1},
    "os": {"Caption": "Microsoft Windows 11 Pro", "Version": "10.0.26100", "SystemDrive": "C:"},
    "bios": {"ReleaseDate": "/Date(1688169600000)/"},
    "chassis": [3],
    "cpu": {"Name": "Intel(R) Xeon(R) w5-2465X", "NumberOfCores": 16, "NumberOfLogicalProcessors": 32},
    "gpu": [{"Name": "NVIDIA RTX 4000 Ada Generation", "AdapterRAM": 4293918720, "DriverVersion": "32.0.15.6094"},
            {"Name": "Microsoft Basic Display Adapter"}],
    "vram": [{"DriverDesc": "NVIDIA RTX 4000 Ada Generation", "HardwareInformation.qwMemorySize": 21474836480}],
    "dimm": [{"Capacity": 34359738368}, {"Capacity": 34359738368}],
    "dimm_slots": 8,
    "pd": [{"FriendlyName": "Samsung SSD 990 PRO 2TB", "MediaType": 4, "BusType": 17, "Size": 2000398934016}],
    "ld": [{"DeviceID": "C:", "FreeSpace": 1099511627776}],
}


class WindowsParseTest(unittest.TestCase):
    def test_workstation(self):
        p = windows.parse_cim(CIM_WORKSTATION)
        self.assertEqual(p["ram_gb"], 64.0)
        self.assertEqual(p["cpu_cores"], 16)
        self.assertEqual(len(p["gpus"]), 1)
        self.assertEqual(p["gpus"][0].vram_gb, 20.0)  # registry value, not the 4 GB AdapterRAM cap
        self.assertEqual(p["disks"][0].medium, "SSD")
        self.assertEqual(p["disks"][0].bus, "NVMe")
        self.assertEqual(p["disks"][0].free_gb, 1024.0)
        self.assertEqual((p["ram_slots_used"], p["ram_slots_total"]), (2, 8))
        self.assertFalse(p["is_laptop"])
        self.assertEqual(p["model_year"], 2023)

    def test_laptop_chassis(self):
        data = dict(CIM_WORKSTATION, chassis=[10])
        self.assertTrue(windows.parse_cim(data)["is_laptop"])


if __name__ == "__main__":
    unittest.main()
