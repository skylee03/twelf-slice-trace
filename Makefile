.PHONY: test selftest selftest-trace demo list build-twelf

test:
	python3 -m unittest discover -s tests -v

selftest:
	python3 selftest.py

selftest-trace:
	python3 selftest.py --trace

build-twelf:
	./scripts/build-twelf-trace.sh

demo:
	./run.sh

list:
	python3 -m twelf_slicer.cli corpus/nat.elf --list
