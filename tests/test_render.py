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

    def test_gif_conversion_displays_the_final_gate_screen(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before = root / 'before.txt'
            before.write_text('$ hw tasks unit\nHE-1 waiting for review\n')
            after = root / 'after.txt'
            after.write_text('$ hw gate unit HE-1\nVERIFIED 1234567\n')
            manifest = root / 'screens.json'
            manifest.write_text(json.dumps([
                {'at': 1, 'path': before.name}, {'at': 1.15, 'path': after.name},
            ]))
            video = root / 'gate.mp4'
            gif = root / 'gate.gif'
            subprocess.check_call([sys.executable, RENDER, manifest, video, '--duration', '30'],
                                  stdout=subprocess.DEVNULL)
            self.ffmpeg('-i', video, '-vf', 'fps=2,scale=960:-1', gif)

            # Compare actual display pixels to rendered captures. The codec and palette can
            # change colors, so each state must be closer to its own capture than the other.
            references = []
            for text in (before, after):
                screen = text.with_suffix('.png')
                subprocess.check_call([sys.executable, RENDER, text, screen], stdout=subprocess.DEVNULL)
                references.append(self.pixels('-i', screen, '-vf', 'scale=1600:-2,scale=960:-1'))
            frames = self.ffmpeg('-i', gif, '-pix_fmt', 'gray', '-f', 'rawvideo', '-')
            frame_size = len(references[0])
            first, last = frames[:frame_size], frames[-frame_size:]
            self.assertLess(self.distance(first, references[0]), self.distance(first, references[1]))
            self.assertLess(self.distance(last, references[1]), self.distance(last, references[0]))
