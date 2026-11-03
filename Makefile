.PHONY: test selftest demo list

test:
	python3 -m unittest discover -s tests -v

selftest:
	python3 selftest.py

demo:
	./run.sh

list:
	python3 -m twelf_slicer.cli corpus/nat.elf --list
