# -*- coding: utf-8 -*-
"""打包 zhDict-<版本>.nvda-addon（版本取自 manifest.ini）。

用法：python tools/build_addon.py [輸出資料夾]   （預設輸出到 repo 根目錄）
發佈時從標籤打包比較保險：git worktree 或 git archive 取出標籤的檔案再執行。
"""
import hashlib
import os
import re
import sys
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
FILES = [
	"manifest.ini",
	"README.md",
	"LICENSE",
	"locale/zh_TW/manifest.ini",
	"globalPlugins/__init__.py",
	"globalPlugins/moeDict/__init__.py",
	"globalPlugins/moeDict/related_words.txt",
]


def main():
	sys.stdout.reconfigure(encoding="utf-8")
	manifest = open(os.path.join(ROOT, "manifest.ini"), encoding="utf-8").read()
	version = re.search(r'^version\s*=\s*"?([^"\n]+)"?', manifest, re.M).group(1).strip()
	outDir = sys.argv[1] if len(sys.argv) > 1 else ROOT
	out = os.path.join(outDir, f"zhDict-{version}.nvda-addon")
	with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
		for f in FILES:
			z.write(os.path.join(ROOT, f), f)
	print(out)
	for f in FILES:
		print("  ", f)
	print("sha256", hashlib.sha256(open(out, "rb").read()).hexdigest())


if __name__ == "__main__":
	main()
