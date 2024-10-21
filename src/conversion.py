import uuid
from jsonpath_ng.jsonpath import Fields, Slice, Where
from jsonpath_ng.ext import parse as parse_ext
import fhir_formatting
import special_values

#Creates a full transaction bundle for a patient at index
def create_transaction_bundle(resource_definition_entities, resource_link_entities, patient_data, index = 0):
    root_bundle = initialize_bundle()
    created_resources = {}
    for resource_definition in resource_definition_entities:
        entity_name = resource_definition['Entity Name']
        #Create and collect fhir resources
        fhir_resource = create_fhir_resource(resource_definition, patient_data, index)
        created_resources[entity_name] = fhir_resource
    #Link resources after creation
    create_resource_links(created_resources, resource_link_entities)
    #Construct into fhir bundle
    for fhir_resource in created_resources.values():
        add_resource_to_transaction_bundle(root_bundle, fhir_resource)
    return root_bundle

#Initialize root bundle definition
def initialize_bundle():
    root_bundle = {}
    root_bundle['resourceType'] = 'Bundle'
    root_bundle['id'] = str(uuid.uuid4())
    root_bundle['type'] = 'transaction'
    root_bundle['entry'] = []
    return root_bundle

# Creates a fhir-json structure from a resource definition entity and the patient_data_sheet
def create_fhir_resource(resource_definition, patient_data, index = 0):
    resource_dict = initialize_resource(resource_definition)
    #Get field entries for this entitiy
    try:
        all_field_entries = patient_data[resource_definition['Entity Name']]
    except KeyError:
        print(f"WARNING: Patient index {index} - Create Fhir Resource Error - {resource_definition['Entity Name']} - No columns for entity '{resource_definition['Entity Name']}' found for resource in 'PatientData' sheet")
        return resource_dict
    #For each field within the entity
    for field_entry in all_field_entries.values():
        #Create a jsonpath from each provided json path and value for this resource
        if field_entry['values'] and len(field_entry['values']) > index:
            create_structure_from_jsonpath(resource_dict, field_entry['jsonpath'], resource_definition, field_entry, field_entry['valueType'], field_entry['values'][index])
    return resource_dict
        
#Initialize a resource from a resource definition. Adding basic 
def initialize_resource(resource_definition):
    initial_resource = {}
    initial_resource['resourceType'] = resource_definition['ResourceType'].strip()
    resource_definition['id'] = str(uuid.uuid4())
    initial_resource['id'] = resource_definition['id'].strip()
    if resource_definition['Profile(s)']:
        initial_resource['meta'] = {
            'profile': resource_definition['Profile(s)']
        }
    return initial_resource

#Create resource references/links with created entities
def create_resource_links(created_resources, resource_link_entites):
    reference_json_block = {
        "reference" : "$value"
    }
    #TODO: Build resource links
    print("Building resource links")
    for resource_link_entity in resource_link_entites:
        try:
            origin_resource = created_resources[resource_link_entity['OriginResource']]
        except KeyError:
            print(f"WARNING: In ResourceLinks tab, found a Origin Resource of : {resource_link_entity['OriginResource']}  but no such entity found in PatientData")
            continue
        try:
            destination_resource = created_resources[resource_link_entity['DestinationResource']]
        except KeyError:
            print(f"WARNING: In ResourceLinks tab, found a Destination Resource of : {resource_link_entity['OriginResource']}  but no such entity found in PatientData")
            continue
        destination_resource_type = created_resources[resource_link_entity['DestinationResource']]['resourceType']
        destination_resource_id = created_resources[resource_link_entity['DestinationResource']]['id']
        origin_resource[resource_link_entity['ReferencePath'].strip().lower()] = reference_json_block
        origin_resource[resource_link_entity['ReferencePath'].strip().lower()]["reference"] = destination_resource_type + "/" + destination_resource_id
    return
    
def add_resource_to_transaction_bundle(root_bundle, fhir_resource):
    entry = {}
    entry['fullUrl'] = "urn:uuid"+fhir_resource['id']
    entry['resource'] = fhir_resource
    entry['request'] = {
      "method": "PUT",
      "url": fhir_resource['resourceType'] + "/" + fhir_resource['id']
    }
    root_bundle['entry'].append(entry)
    return root_bundle

#Drill down and create a structure from a json path with a simple recurisve process
# Supports 2 major features:
# 1) dot notation such as $.codeableconcept.coding[0].value = 1234
# 2) simple qualifiers such as $.name[use=official].family = Dickerson
# rootStruct: top level structure to drill into
# json_path: dotnotation path to    
def create_structure_from_jsonpath(root_struct, json_path, resource_definition, entity_definition, dataType, value):
    #Get all dot notation components as seperate 
    if dataType is not None and dataType.strip().lower() == 'string':
        value = str(value)
    #Local Helper function to quickly recurse and return the next level of structure. Used by main recursive function
    def _build_structure_recurse(current_struct, parts, value, previous_parts, part):
        previous_parts.append(part)
        return_struct = _build_structure(current_struct, parts[1:], value, previous_parts)
        return return_struct
        
    #Local main recursive function to drill into the json structure, assign paths, and create structure where needed
    def _build_structure(current_struct, parts, value, previous_parts):
        if len(parts) == 0:
            return current_struct
        #Grab current part
        part = parts[0]
        #SPECIAL HANDLING CLAUSE 
        if json_path in special_values.custom_handlers:
            return special_values.custom_handlers[json_path].assign_value(current_struct,part,value)
        #Ignore dollar sign ($) and drill farther down
        if part == '$' or part == resource_definition['ResourceType']:
            #Ignore the dollar sign and the resourcetype
            return _build_structure_recurse(current_struct, parts, value, previous_parts, part)
        
        # If parts length is one then this is the final key to access and pair
        if len(parts) == 1:
            #Check for numeic qualifier '[0]' and '[1]'
            if '[' in part and ']' in part:
            #Seperate the key from the qualifier
                key_part = part[:part.index('[')]
                qualifier = part[part.index('[')+1:part.index(']')]
                qualifier_condition = qualifier.split('=')
                
                #If there is no key part, aka '[0]', '[1]' etc, then it's a simple accessor
                if key_part is None or key_part == '':
                    if not qualifier.isdigit():
                        raise TypeError(f"ERROR: Full jsonpath: {json_path} - current path - {'.'.join(previous_parts + parts[:1])} - qualifier - {qualifier} - standalone qualifier expected to be a single index numeric ([0], [1], etc)")
                    if current_struct == {}:
                        current_struct = []
                    if not isinstance(current_struct, list):
                        raise TypeError(f"ERROR: Full jsonpath: {json_path} - current path - {'.'.join(previous_parts + parts[:1])} - Expected a list, but got {type(current_struct).__name__} instead.")
                    part = int(qualifier)
                    if part + 1 > len(current_struct):
                        current_struct.extend({} for x in range (part + 1 - len(current_struct)))
            #Actual assigning to the path
            fhir_formatting.assign_value(current_struct, part, value, entity_definition['valueType'])
            return current_struct
        
        # If there is a simple qualifier with '['and ']'
        elif '[' in part and ']' in part:
            #Seperate the key from the qualifier
            key_part = part[:part.index('[')]
            qualifier = part[part.index('[')+1:part.index(']')]
            qualifier_condition = qualifier.split('=')
            
            #If there is no key part, aka '[0]', '[1]' etc, then it's a simple accessor
            if key_part is None or key_part == '':
                if not qualifier.isdigit():
                    raise TypeError(f"ERROR: Full jsonpath: {json_path} - current path - {'.'.join(previous_parts + parts[:1])} - qualifier - {qualifier} - standalone qualifier expected to be a single index numeric ([0], [1], etc)")
                if current_struct == {}:
                    current_struct = []
                if not isinstance(current_struct, list):
                    raise TypeError(f"ERROR: Full jsonpath: {json_path} - current path - {'.'.join(previous_parts + parts[:1])} - Expected a list, but got {type(current_struct).__name__} instead.")
                qualifier_as_number = int(qualifier)
                if qualifier_as_number + 1 > len(current_struct):
                    current_struct.extend({} for x in range (qualifier_as_number + 1 - len(current_struct)))
                inner_struct = current_struct[qualifier_as_number]
                inner_struct = _build_structure_recurse(inner_struct, parts, value, previous_parts, part)
                current_struct[qualifier_as_number] = inner_struct
                return current_struct
            # Create the key part in the structure
            if (not key_part in current_struct) or (isinstance(current_struct[key_part], dict)):
                current_struct[key_part] = []
            #If there is a key_part and the If the qualifier condition is defined
            elif len(qualifier_condition) == 2:
                qualifier_key, qualifier_value = qualifier_condition
                # Retrieve an inner structure if it exists allready that matches the criteria
                inner_struct = next((innerElement for innerElement in current_struct[key_part] if isinstance(innerElement, dict) and innerElement.get(qualifier_key) == qualifier_value), None)
                #If no inner structure exists, create one instead
                if inner_struct is None:
                    inner_struct = {qualifier_key: qualifier_value}
                    current_struct[key_part].append(inner_struct)
                #Recurse into that innerstructure where the qualifier matched to continue the part traversal
                inner_struct = _build_structure_recurse(inner_struct, parts, value, previous_parts, part)
                return current_struct
            #If there's no qualifier condition, but an index aka '[0]', '[1]' etc, then it's a simple accessor
            elif qualifier.isdigit():
                if not isinstance(current_struct[key_part], list):
                    raise TypeError(f"ERROR: Full jsonpath: {json_path} - current path - {'.'.join(previous_parts + parts[0])} - Expected a list, but got {type(current_struct).__name__} instead.")
                qualifier_as_number = int(qualifier)
                if qualifier_as_number > len(current_struct):
                    current_struct[key_part].extend({} for x in range (qualifier_as_number - len(current_struct)))
                inner_struct = current_struct[key_part][qualifier_as_number]
                inner_struct = _build_structure_recurse(inner_struct, parts, value, previous_parts, part)
                current_struct[key_part][qualifier_as_number] = inner_struct
                return current_struct
        #None qualifier accessor
        else:
            if(part not in current_struct):
                current_struct[part] = {}
            inner_struct = _build_structure_recurse(current_struct[part], parts, value, previous_parts, part)
            current_struct[part] = inner_struct
            return current_struct
    
    if value == None:
        print(f"WARNING: Full jsonpath: {json_path} - Expected to find a value but found None instead")
        return root_struct
    #Start of top-level function which calls the enclosed recursive function
    parts = json_path.split('.')
    return _build_structure(root_struct, parts, value, [])