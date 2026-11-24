import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


RENDER = Path(__file__).resolve().parents[1] / '.agents/skills/verify-herdworks/scripts/render.py'


@unittest.skipUnless(shutil.which('ffmpeg'), 'terminal media rendering requires FFmpeg')
class RenderTests(unittest.TestCase):
    def ffmpeg(self, *args):
        return subprocess.check_output(['ffmpeg', '-nostdin', '-loglevel', 'error', *args])

    def pixels(self, *args):
        return self.ffmpeg(*args, '-frames:v', '1', '-pix_fmt', 'gray', '-f', 'rawvideo', '-')

    def distance(self, actual, expected):
        self.assertTrue(actual)
        self.assertEqual(len(actual), len(expected))
        return sum(abs(a - b) for a, b in zip(actual, expected))

    def test_motion_displays_both_gate_states_when_output_adds_a_line(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before = root / 'before.txt'
            before.write_text('$ hw tasks unit\nHE-1 waiting for review\n')
            after = root / 'after.txt'
            after.write_text('$ hw tasks unit\nHE-1 verified\nVERIFIED 1234567\n')
            manifest = root / 'screens.json'
            manifest.write_text(json.dumps([
                {'at': 1, 'path': before.name}, {'at': 1.15, 'path': after.name},
            ]))
            video = root / 'gate.mp4'
            gif = root / 'gate.gif'
            subprocess.check_call([sys.executable, RENDER, manifest, video, '--duration', '30'],
                                  stdout=subprocess.DEVNULL)
            self.ffmpeg('-i', video, '-vf', 'fps=2,scale=960:-1', gif)

            # Pad the reference separately. The manifest deliberately has unequal line counts.
            padded_before = root / 'padded-before.txt'
            padded_before.write_text(before.read_text() + '\n')
            screens = []
            for text in (padded_before, after):
                screen = text.with_suffix('.png')
                subprocess.check_call([sys.executable, RENDER, text, screen], stdout=subprocess.DEVNULL)
                screens.append(screen)

            # Encoding can change colors. Each decoded state should match its own capture better.
            for media, filters in ((video, 'scale=1600:-2'), (gif, 'scale=1600:-2,scale=960:-1')):
                with self.subTest(media=media.suffix):
                    before_pixels, after_pixels = [
                        self.pixels('-i', screen, '-vf', filters) for screen in screens
                    ]
                    frames = self.ffmpeg('-i', media, '-pix_fmt', 'gray', '-f', 'rawvideo', '-')
                    frame_size = len(before_pixels)
                    first, last = frames[:frame_size], frames[-frame_size:]
                    self.assertLess(self.distance(first, before_pixels), self.distance(first, after_pixels))
                    self.assertLess(self.distance(last, after_pixels), self.distance(last, before_pixels))
