SITES = neuprint_JRC_Hemibrain_1point1

all: $(patsubst %, %_connectomics.owl, $(SITES))

%_template.tsv:
	python -m VFB_connectomics_import.script_runner % $@ # Hmmm - maybe we have a problem here.  Need blank targets?

%_connectomics.owl: %_template.tsv
 	robot template -i helper.owl --add-prefix "n2o: http://neo2owl/custom/" \
       --add-prefix "VFB: http://virtualflybrain.org/reports/VFB_"  --template >$  \
       annotate --ontology-iri "http://virtualflybrain.org/data/VFB/OWL/"%.owl \
       convert -f ofn -o %_connectomics.owl