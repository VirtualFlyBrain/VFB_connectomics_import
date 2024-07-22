# #    Functions for grabbing FlyWire neurons, including meshes/skeletons/connectivity/annotations
# #    Warning: be careful with versions and rootid mappings for this dataset. Contact Philipp Schlegel at FlyWire for up to date advice (suggest using slack)
#
# from fafbseg import flywire
# import navis
# import pandas as pd
# import flybrains
# import os
# from vfb_connect.cross_server_tools import VfbConnect
#
# #setup flywire credentials
# #flywire.set_chunkedgraph_secret("47576875e49eeb999396a0e73de0cf31")
#
# #setup flywire default dataset - in the future hopefully this will just be prod
# #flywire.set_default_dataset('flat_630')
#
# def generate_curation_tsv(annotations_tsv_path):
#     '''generate anat_ tsv for loading neuprint neurons via the VFB curation interface
#
#     Parameters
#     ----------
#     query  :        string
#                     Cypher query for neuprint, must return neuron node(s)
#     '''
#
#     #we're using an intermediate release here so there is no matching materialisation. So we need to load our csv from Philipp, map back to mat 630 and then load from those root_ids. ez pz.
#     neuron_annotations_df = pd.read_csv(annotations_tsv_path, sep='\t')
#     neuron_annotations_df.dropna(subset='vfb_id', inplace=True)
#
#     ## map back to 630 and drop those that don't - this uses supervoxels
#     mapped_ids=flywire.supervoxels_to_roots(neuron_annotations_df.supervoxel_id, timestamp='mat_630')
#
#     ## add mapped ids to df and compare to current ids, check for dups
#     neuron_annotations_df['root_630_u'] = mapped_ids
#
#     #which ones are inconsistent between Philipps mapping to 630 and mine
#     all(neuron_annotations_df['root_630'] == neuron_annotations_df['root_630_u']) # why is this not true only for 82899260193955748 is this false
#     neuron_annotations_df[neuron_annotations_df['root_630_u'] != neuron_annotations_df['root_630']] ##TODO have a look at where a single 630 neuron maps to many in current. (looks like visual mashed together so far) - confirmed many are visual and many are not on the codex, presumably for the same reason. will drop these for now
#
#     # find dups
#     neuron_annotations_df['root_630_u'].value_counts()
#     mat_630_dups = neuron_annotations_df[neuron_annotations_df['root_630_u'].duplicated(keep=False)].sort_values(by='root_630_u')
#
#     #drop dups TODO check with robbie if this needs to be expanded into something smarter
#     neurons_df = neuron_annotations_df[~neuron_annotations_df['root_630_u'].duplicated(keep=False)]
#
#     # make curation tsv
#     curation_tsv = pd.DataFrame()
#     curation_tsv['anat_id'] = 'VFB_' + neurons_df[['vfb_id']]
#     curation_tsv['filename'] = neurons_df[['root_630_u']]
#     curation_tsv['is_a'] = 'adult neuron'
#     curation_tsv['part_of'] = 'female organism|adult brain'
#     curation_tsv['label'] = 'FlyWire:' + neurons_df['root_id'].astype(str) #TODO is there an instance name?
#     curation_tsv['comment'] = ''
#     curation_tsv['comment'][~neurons_df['status'].isna()] = 'status-' + neurons_df['status']
#     neurons_df.fillna('None', inplace=True)
#     curation_tsv['comment'] = curation_tsv['comment'] + 'FlyWire classification: flow-' + neurons_df['flow'].astype(str) + ', superclass-' + neurons_df['super_class'].astype(str) + ', class-' + neurons_df['cell_class'].astype(str) + ', subclass-' + neurons_df['cell_sub_class'].astype(str) + ', cell type-' + neurons_df['cell_type'].astype(str)+ ', hemibrain type-' + neurons_df['hemibrain_type'].astype(str)
#     curation_tsv['comment'] = curation_tsv['comment'] + '. FBbt_id annotation-' + neurons_df['fbbt_id'].astype(str)
#     curation_tsv['comment'] = curation_tsv['comment'] + '. supervoxel id-' + neurons_df['supervoxel_id'].astype(str)
#     #TODO consider supervoxel will go to internal api node
#     curation_tsv['dbxrefs'] = 'flywire:' + neurons_df['root_630_u'].astype(str) + '|' + 'flywire_supervoxel:' + neurons_df['supervoxel_id'].astype(str)
#
#     return curation_tsv
#
# annotations_tsv_path = '/Users/adm/Documents/GitHub/VFB_connectomics_import/src/VFB_connectomics_import/resources/Supplemental_file1_annotations.tsv'
# curation_tsv=generate_curation_tsv(annotations_tsv_path)
# curation_tsv.to_csv('Dorkenwald2023_curation.tsv', sep='\t', index=False)
#
# ##### scraps for testing skels/meshes, code runs on jenkins (url tbd).
# ## testing neuron obj sizes
# testset = list(curation_tsv.filename[0:100])
# k = flywire.get_mesh_neuron(testset, dataset='flat_630')
# s = flywire.get_skeletons(testset) #only works for 630 so no need to specify dataset
#
# ## APL test TODO try aligning as for manc
# m = flywire.get_mesh_neuron(720575940621280688)
# n = flywire.get_skeletons(720575940621280688)
#
# m = flywire.get_mesh_neuron(720575940606577414, dataset='flat_630')
# n = flywire.get_skeletons(720575940606577414)
#
# ## plotting
# navis.plot3d([k[0:10]],backend='plotly').show(renderer='browser')
#
#
# #transforming
# flybrains.download_jrc_transforms()
# flybrains.register_transforms()
# transformed_neuron = navis.xform_brain(k[0:10], source='FLYWIRE', target='JRC2018U')
# #plot transformed against mesh
# navis.plot3d([transformed_neuron, flybrains.JRC2018U],backend='plotly').show(renderer='browser')
#
# ## writing
# navis.write_mesh(m,filepath='test.obj')
# navis.write_swc(n, filepath='test.swc')
#
# ## read swc from local file (should have fixed somata)
# a=navis.read_swc('/Users/adm/Downloads/sk_lod1_630_healed_ds2/720575940621280688.swc')
#
# # test if all of the filenames exist in the local files (using mat 630 ids so should map to the meshes 1:1)
# for neuron in curation_tsv.filename:
#     filepath = '/Users/adm/Downloads/sk_lod1_630_healed_ds2/'+str(neuron)+'.swc'
#     try:
#         navis.read_swc(filepath)
#     except Exception as e: print(e)



###
#!.pyenv/bin/python3.9

import os
import glob
import numpy as np
import navis
import flybrains
import pandas as pd
import cloudvolume
import sys
from vfb_connect.cross_server_tools import VfbConnect
import multiprocessing
from multiprocessing import Pool
import threading
from fafbseg import flywire

os.getenv('OUTPUT_FOLDER')

def delete_volume_files(local_folder_path):
    """
    Delete all files matching the pattern "volume.*" in the specified folder.
    :param local_folder_path: str, path to the folder containing the files to delete
    """
    # Ensure the path ends with a separator
    if not local_folder_path.endswith(os.sep):
        local_folder_path += os.sep

    # Generate file paths for all files matching the pattern "volume.*" in the specified folder
    file_paths = glob.glob(f'{local_folder_path}volume*')
    file_paths += glob.glob(f'{local_folder_path}thumbnail*')
    # Delete each file
    for file_path in file_paths:
        try:
            os.remove(file_path)
            print(f'Successfully deleted {file_path}')
        except Exception as e:
            print(f'Could not delete {file_path}: {e}')

# Download the JRC transforms
flybrains.download_jrc_transforms()

# Register the downloaded transforms
flybrains.register_transforms()

# Setup connection to the VFB Neo4j database
kbw = VfbConnect(neo_endpoint='http://kb.virtualflybrain.org:80', neo_credentials=('neo4j', os.environ.get('password')))

kbw = VfbConnect(neo_endpoint='http://kb.virtualflybrain.org:80')

# Your Cypher query
cypher_query = '''
MATCH (d:DataSet {short_form:'Dorkenwald2023'})<-[:has_source]-(i:Individual)<-[:depicts]-(ic:Individual)
-[r:in_register_with]->(tc:Template)
RETURN r.filename[0] as root_id, r.folder[0] as folder
'''

# Execute the Cypher query using the commit_list method
output = kbw.nc.commit_list(statements=[cypher_query])

# Check for errors in the response
if output is False or not output:
    print("An error occurred while executing the Cypher query.")
    exit(1)  # Exit the script in case of an error

# Access the data key of the first item in the output list
query_data_df=pd.DataFrame(output[0]['data'])['row'].apply(pd.Series)

# Get the total number of items to process
total_items = len(query_data_df[0])

# Process the results
for index, result in query_data_df.iterrows():
    print(f"Processing item {index + 1} of {total_items}")
    # Access the row key of each result item to get the root_id and folder values
    root_id, folder_url = result
    folder_url = folder_url.replace('http://www.virtualflybrain.org/data/', '/IMAGE_WRITE/')

    # Create the local folder if it doesn't exist
    local_folder_path = os.path.dirname(folder_url)
    os.makedirs(local_folder_path, exist_ok=True)

    # Path for the output SWC file
    filename = os.path.join(local_folder_path, f"volume.swc")

    # Path for the output obj file
    mesh_filename = os.path.join(local_folder_path, f"volume_man.obj")

    # Check if the output file already exists, if so, skip to the next iteration
    if os.path.exists(filename) and os.path.exists(mesh_filename):
        # Redo files if requested
        if os.environ.get('redo') == 'true':
            print(f"File for neuron {root_id} swc and obj already exists. Removing old versions...")
            delete_volume_files(local_folder_path)
        else:
            print(f"File for neuron {root_id} swc or obj already exists. Skipping...")
            continue #skipping nrrd for now
            if os.path.exists(nrrd_filename):
                continue

    if os.path.exists(filename) or os.path.exists(mesh_filename):
        # Redo files if requested
        if os.environ.get('redo') == 'true':
            print(f"File for neuron {root_id} swc or obj already exists. Removing old versions...")
            delete_volume_files(local_folder_path)

    try:
        if not os.path.exists(filename):
            # Download skeleton
            ### this needs to be the path to the local 'sk_lod1_630_healed_ds2' folder + the root_id - ex 'c/sk_lod1_630_healed_ds2/720575940621280688.swc'
            neuron = navis.read_swc('sk_lod1_630_healed_ds2' + root_id)

            # Transform neuron data from FlyWire to JRC2018U
            transformed_neuron = navis.xform_brain(neuron, source='FLYWIRE', target='JRC2018U')
            # Check for warnings
            if not transformed_neuron:
                print(f"Warning: No skeleton data available for neuron {root_id}. Possibly outside the H5 deformation field.")
                continue  # Skip to the next iteration
            # Save to SWC file
            navis.write_swc(transformed_neuron, filename)
            print(f"Written to {filename.replace('/IMAGE_WRITE/', 'http://www.virtualflybrain.org/data/')}")
        else:
            print(f"File for neuron {root_id} swc already exists. Skipped...")
    except Exception as e:
        print(f"Warning: Failed to process neuron {root_id}. Error: {e}")
    try:
        if not os.path.exists(mesh_filename):
            # Download mesh
            mesh_neuron = flywire.get_mesh_neuron(root_id, dataset='flat_630', omit_failures=True)

            # Transform neuron mesh data from FlyWire to JRC2018U
            transformed_mesh_neuron = navis.xform_brain(mesh_neuron, source='FLYWIRE', target='JRC2018U')
            # Check for warnings
            if not transformed_mesh_neuron:
                print(f"Warning: No mesh data available for neuron {root_id}. Possibly outside the H5 deformation field.")
                continue  # Skip to the next iteration
            # Save to obj file
            navis.write_mesh(transformed_mesh_neuron, mesh_filename)
            print(f"Written to {mesh_filename.replace('/IMAGE_WRITE/', 'http://www.virtualflybrain.org/data/')}")
        else:
            print(f"File for neuron {root_id} obj already exists. Skipped...")
    except Exception as e:
        print(f"Warning: Failed to process neuron {root_id}. Error: {e}")