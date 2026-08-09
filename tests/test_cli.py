from __future__ import annotations

import unittest

from halyk_agent.cli import build_parser


class CliDefaultsTests(unittest.TestCase):
    def test_live_eval_defaults_to_openai_only(self) -> None:
        args = build_parser().parse_args(
            [
                "live-eval",
                "dataset",
                "--documents-dir",
                "documents",
                "--output-dir",
                "run",
            ]
        )
        self.assertEqual(args.providers, ("openai",))

    def test_stability_eval_defaults_to_openai_only(self) -> None:
        args = build_parser().parse_args(
            [
                "stability-eval",
                "dataset",
                "--documents-dir",
                "documents",
                "--output-dir",
                "run",
            ]
        )
        self.assertEqual(args.providers, ("openai",))


if __name__ == "__main__":
    unittest.main()
