import logging
import os
import json
import pickle
import itertools
from d3m_ta2_nyu.workflow import database
from d3m import index
from d3m.container import Dataset, DataFrame, ndarray, List
from d3m_ta2_nyu.utils import is_collection, get_collection_type


# Use a headless matplotlib backend
os.environ['MPLBACKEND'] = 'Agg'
logger = logging.getLogger(__name__)

CONTAINER_CAST = {
    Dataset: {
        DataFrame: 'd3m.primitives.data_transformation.dataset_to_dataframe.Common',
        ndarray: ('d3m.primitives.data_transformation.dataset_to_dataframe.Common'
                  '|d3m.primitives.data_transformation.dataframe_to_ndarray.Common'),
        List: ('d3m.primitives.data_transformation.dataset_to_dataframe.Common'
               '|d3m.primitives.data_transformation.dataframe_to_list.Common')
    },
    DataFrame: {
        Dataset: "",
        ndarray: 'd3m.primitives.data_transformation.dataframe_to_ndarray.Common',
        List: 'd3m.primitives.data_transformation.dataframe_to_list.Common'
    },
    ndarray: {
        Dataset: "",
        DataFrame: 'd3m.primitives.data_transformation.ndarray_to_dataframe.Common',
        List: 'd3m.primitives.data_transformation.ndarray_to_list.Common'
    },
    List: {
        Dataset: "",
        DataFrame: 'd3m.primitives.data_transformation.list_to_dataframe.Common',
        ndarray: 'd3m.primitives.data_transformation.list_to_ndarray.Common',
    }
}


def make_pipeline_module(db, pipeline, name, package='d3m', version='2019.10.10'):
    pipeline_module = database.PipelineModule(pipeline=pipeline, package=package, version=version, name=name)
    db.add(pipeline_module)
    return pipeline_module


def make_data_module(db, pipeline, targets, features):
    input_data = make_pipeline_module(db, pipeline, 'dataset', 'data', '0.0')
    db.add(database.PipelineParameter(
        pipeline=pipeline, module=input_data,
        name='targets', value=pickle.dumps(targets),
    ))
    db.add(database.PipelineParameter(
        pipeline=pipeline, module=input_data,
        name='features', value=pickle.dumps(features),
    ))
    return input_data


def connect(db, pipeline, from_module, to_module, from_output='produce', to_input='inputs'):
    if 'index' not in from_output:
        if not from_module.name.startswith('dataset'):
            from_module_primitive = index.get_primitive(from_module.name)
            from_module_output = from_module_primitive.metadata.query()['primitive_code']['class_type_arguments'][
                'Outputs']
        else:
            from_module_output = Dataset

        to_module_primitive = index.get_primitive(to_module.name)
        to_module_input = to_module_primitive.metadata.query()['primitive_code']['class_type_arguments'][
            'Inputs']

        arguments = to_module_primitive.metadata.query()['primitive_code']['arguments']

        if to_input not in arguments:
             raise NameError('Argument %s not found in %s' % (to_input, to_module.name))

        if from_module_output != to_module_input and \
                from_module.name != 'd3m.primitives.data_transformation.audio_reader.DistilAudioDatasetLoader':  # TODO Find a better way
            cast_module_steps = CONTAINER_CAST[from_module_output][to_module_input]
            if cast_module_steps:
                for cast_step in cast_module_steps.split('|'):
                    cast_module = make_pipeline_module(db, pipeline,cast_step)
                    db.add(database.PipelineConnection(pipeline=pipeline,
                                                       from_module=from_module,
                                                       to_module=cast_module,
                                                       from_output_name=from_output,
                                                       to_input_name='inputs'))
                    from_module = cast_module
            else:
                raise TypeError('Incompatible connection types: %s and %s' % (str(from_module_output), str(to_module_input)))

    db.add(database.PipelineConnection(pipeline=pipeline,
                                       from_module=from_module,
                                       to_module=to_module,
                                       from_output_name=from_output,
                                       to_input_name=to_input))


def set_hyperparams(db, pipeline, module, **hyperparams):
    db.add(database.PipelineParameter(
        pipeline=pipeline, module=module,
        name='hyperparams', value=pickle.dumps(hyperparams),
    ))


def change_default_hyperparams(db, pipeline, primitive_name, primitive):
    if primitive_name == 'd3m.primitives.feature_extraction.tfidf_vectorizer.SKlearn':
        set_hyperparams(db, pipeline, primitive, use_semantic_types=True, return_result='replace')
    elif primitive_name == 'd3m.primitives.feature_extraction.count_vectorizer.SKlearn':
        set_hyperparams(db, pipeline, primitive, use_semantic_types=True, return_result='replace')
    elif primitive_name == 'd3m.primitives.feature_extraction.feature_agglomeration.SKlearn':
        set_hyperparams(db, pipeline, primitive, use_semantic_types=True, return_result='replace')
    elif primitive_name == 'd3m.primitives.data_cleaning.string_imputer.SKlearn':
        set_hyperparams(db, pipeline, primitive, use_semantic_types=True, return_result='replace')
    elif primitive_name == 'd3m.primitives.data_transformation.one_hot_encoder.SKlearn':
        set_hyperparams(db, pipeline, primitive, use_semantic_types=True, return_result='replace', handle_unknown='ignore')
    elif primitive_name == 'd3m.primitives.data_cleaning.imputer.SKlearn':
        set_hyperparams(db, pipeline, primitive, strategy='most_frequent')
    elif primitive_name == 'd3m.primitives.clustering.k_means.DistilKMeans':
        set_hyperparams(db, pipeline, primitive, cluster_col_name='Class')
    elif primitive_name == 'd3m.primitives.time_series_forecasting.lstm.DeepAR':
        set_hyperparams(db, pipeline, primitive, epochs=1)
    elif primitive_name == 'd3m.primitives.data_transformation.encoder.DSBOX':
        set_hyperparams(db, pipeline, primitive, n_limit=50)
    elif primitive_name == 'd3m.primitives.data_cleaning.cleaning_featurizer.DSBOX':
        set_hyperparams(db, pipeline, primitive, features='split_date_column')
    elif primitive_name == 'd3m.primitives.data_transformation.encoder.DistilTextEncoder':
        set_hyperparams(db, pipeline, primitive, encoder_type='tfidf')
    elif primitive_name == 'd3m.primitives.classification.text_classifier.DistilTextClassifier':
        set_hyperparams(db, pipeline, primitive, metric='accuracy')
    elif primitive_name == 'd3m.primitives.feature_selection.joint_mutual_information.AutoRPI':
        set_hyperparams(db, pipeline, primitive, method='fullBayesian')


def need_entire_dataframe(primitives):
    for primitive in primitives:
        if primitive in {'d3m.primitives.data_transformation.time_series_to_list.DSBOX',
                         'd3m.primitives.feature_extraction.random_projection_timeseries_featurization.DSBOX',
                         'd3m.primitives.data_transformation.dataframe_to_tensor.DSBOX',
                         'd3m.primitives.feature_extraction.resnet50_image_feature.DSBOX'}:
            return True
    return False


def encode_features(pipeline, attribute_step, target_step, features_metadata, db):
    last_step = attribute_step
    feature_types = features_metadata['only_attribute_types']
    count_steps = 0
    if 'http://schema.org/Text' in feature_types:
        text_step = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.encoder.DistilTextEncoder')
        set_hyperparams(db, pipeline, text_step, encoder_type='tfidf')
        connect(db, pipeline, last_step, text_step)
        connect(db, pipeline, target_step, text_step, to_input='outputs')
        last_step = text_step
        count_steps += 1

    if 'http://schema.org/DateTime' in feature_types:
        time_step = make_pipeline_module(db, pipeline,
                                         'd3m.primitives.data_transformation.enrich_dates.DistilEnrichDates')
        connect(db, pipeline, last_step, time_step)
        last_step = time_step
        count_steps += 1

    if 'https://metadata.datadrivendiscovery.org/types/CategoricalData' in feature_types:
        onehot_step = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.encoder.DSBOX')
        set_hyperparams(db, pipeline, onehot_step, n_limit=50)
        connect(db, pipeline, last_step, onehot_step)
        last_step = onehot_step
        count_steps += 1

    return last_step, count_steps


def process_template(db, input_data, pipeline, pipeline_template, count_template_steps=0, prev_step=None):
    prev_steps = {}
    for pipeline_step in pipeline_template['steps']:
        if pipeline_step['type'] == 'PRIMITIVE':
            step = make_pipeline_module(db, pipeline, pipeline_step['primitive']['python_path'])
            if 'outputs' in pipeline_step:
                for output in pipeline_step['outputs']:
                    prev_steps['steps.%d.%s' % (count_template_steps, output['id'])] = step

            count_template_steps += 1
            if 'hyperparams' in pipeline_step:
                hyperparams = {}
                for hyper, desc in pipeline_step['hyperparams'].items():
                    hyperparams[hyper] = {'type': desc['type'], 'data': desc['data']}
                set_hyperparams(db, pipeline, step, **hyperparams)
        else:
            # TODO In the future we should be able to handle subpipelines
            break
        if prev_step:
            if 'arguments' in pipeline_step:
                for argument, desc in pipeline_step['arguments'].items():
                    connect(db, pipeline, prev_steps[desc['data']], step,
                            from_output=desc['data'].split('.')[-1], to_input=argument)
            # index is a special connection to keep the order of steps in fixed pipeline templates
            connect(db, pipeline, prev_step, step, from_output='index', to_input='index')
        else:
            connect(db, pipeline, input_data, step, from_output='dataset')
        prev_step = step

    return prev_step, count_template_steps


def add_semantic_types(db, features_metadata, pipeline, pipeline_template, prev_step):
    count_steps = 0
    if pipeline_template is None:
        for semantic_type, columns in features_metadata['semantictypes_indices'].items():
            step_add_type = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                               'add_semantic_types.Common')
            count_steps += 1
            set_hyperparams(db, pipeline, step_add_type, columns=columns, semantic_types=[semantic_type])
            connect(db, pipeline, prev_step, step_add_type)
            prev_step = step_add_type
    else:
        step_add_type = make_pipeline_module(db, pipeline, 'd3m.primitives.schema_discovery.'
                                                           'profiler.Common')
        count_steps += 1
        connect(db, pipeline, prev_step, step_add_type)
        prev_step = step_add_type
    return prev_step, count_steps


def add_file_readers(db, pipeline, prev_step, dataset_path):
    last_step = prev_step
    count_steps = 0
    if get_collection_type(dataset_path) == 'text':
        text_reader = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.text_reader.Common')
        count_steps += 1
        set_hyperparams(db, pipeline, text_reader, return_result='replace')
        connect(db, pipeline, prev_step, text_reader)
        last_step = text_reader

    elif get_collection_type(dataset_path) == 'image':
        image_reader = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.image_reader.Common')
        count_steps += 1
        set_hyperparams(db, pipeline, image_reader, return_result='replace')
        connect(db, pipeline, prev_step, image_reader)
        last_step = image_reader

    elif get_collection_type(dataset_path) == 'audio':
        audio_reader = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.audio_reader.Common')
        count_steps += 1
        set_hyperparams(db, pipeline, audio_reader, return_result='replace')
        connect(db, pipeline, prev_step, audio_reader)
        last_step = audio_reader

    return last_step, count_steps


def add_previous_primitive(db, pipeline, primitives, prev_step):
    remaining_primitives = []
    count_steps = 0
    for primitive in primitives:
        if need_entire_dataframe([primitive]):
            step_add_type = make_pipeline_module(db, pipeline, primitive)
            count_steps += 1
            connect(db, pipeline, prev_step, step_add_type)
            prev_step = step_add_type
        else:
            remaining_primitives.append(primitive)

    return prev_step, remaining_primitives, count_steps


class BaseBuilder:

    def make_d3mpipeline(self, primitives, origin, dataset, pipeline_template, targets, features,
                         features_metadata, privileged_data=[], metrics=[], DBSession=None):
        # TODO parameters 'features and 'targets' are not needed
        db = DBSession()
        dataset_path = dataset[7:]
        origin_name = '%s (%s)' % (origin, ', '.join([p.replace('d3m.primitives.', '') for p in primitives]))
        pipeline = database.Pipeline(origin=origin_name, dataset=dataset)

        try:
            input_data = make_data_module(db, pipeline, targets, features)

            step0 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.denormalize.Common')
            count_steps = 0
            if pipeline_template:
                template_step, template_count = process_template(db, input_data, pipeline, pipeline_template)
                count_steps += template_count
                connect(db, pipeline, template_step, step0)
            else:
                connect(db, pipeline, input_data, step0, from_output='dataset')

            step1 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.dataset_to_dataframe.Common')
            count_steps += 1
            connect(db, pipeline, step0, step1)

            prev_step = step1
            if is_collection(dataset_path) and not need_entire_dataframe(primitives):
                prev_step, reader_steps = add_file_readers(db, pipeline, prev_step, dataset_path)
                count_steps += reader_steps

            if len(features_metadata['semantictypes_indices']) > 0:
                prev_step, semantic_steps = add_semantic_types(db, features_metadata, pipeline, pipeline_template,
                                                               prev_step)
                count_steps += semantic_steps

            dataframe_step = prev_step

            if 'ROC_AUC' in metrics[0]['metric'].name:
                step_unique = make_pipeline_module(db, pipeline, 'd3m.primitives.operator.compute_unique_values.Common')
                connect(db, pipeline, dataframe_step, step_unique)
                count_steps += 1
                prev_step = step_unique
            else:
                step_unique = dataframe_step

            if need_entire_dataframe(primitives):
                prev_step, primitives, primitive_steps = add_previous_primitive(db, pipeline, primitives, prev_step)
                count_steps += primitive_steps




            step2 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.column_parser.Common')
            count_steps += 1
            connect(db, pipeline, prev_step, step2)

            step3 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                       'extract_columns_by_semantic_types.Common')
            count_steps += 1
            set_hyperparams(db, pipeline, step3,
                            semantic_types=['https://metadata.datadrivendiscovery.org/types/Attribute'],
                            exclude_columns=privileged_data)
            connect(db, pipeline, step2, step3)

            step4 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                       'extract_columns_by_semantic_types.Common')
            count_steps += 1
            set_hyperparams(db, pipeline, step4,
                            semantic_types=['https://metadata.datadrivendiscovery.org/types/TrueTarget'])
            connect(db, pipeline, step_unique, step4)

            current_step = prev_step = step3

            for primitive in primitives:
                current_step = make_pipeline_module(db, pipeline, primitive)
                count_steps += 1
                change_default_hyperparams(db, pipeline, primitive, current_step)
                connect(db, pipeline, prev_step, current_step)
                prev_step = current_step

                to_module_primitive = index.get_primitive(primitive)
                if 'outputs' in to_module_primitive.metadata.query()['primitive_code']['arguments']:
                    connect(db, pipeline, step4, current_step, to_input='outputs')

            if 'ROC_AUC' in metrics[0]['metric'].name:
                step5 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'construct_confidence.Common')
                set_hyperparams(db, pipeline, step5,
                                primitive_learner={"type": "PRIMITIVE", "data": count_steps}
                                )
                connect(db, pipeline, current_step, step5, from_output='index', to_input='index')
                connect(db, pipeline, step_unique, step5)
                connect(db, pipeline, dataframe_step, step5, to_input='reference')
            else:
                step5 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'construct_predictions.Common')
                connect(db, pipeline, current_step, step5)
                connect(db, pipeline, dataframe_step, step5, to_input='reference')


            db.add(pipeline)
            db.commit()
            logger.info('%s PIPELINE ID: %s', origin, pipeline.id)
            return pipeline.id
        except:
            logger.exception('Error creating pipeline id=%s, primitives=%s', pipeline.id, str(primitives))
            return None
        finally:
            db.close()

    @staticmethod
    def make_template(imputer, estimator, dataset, pipeline_template, targets, features, features_metadata,
                      privileged_data, metrics,  DBSession=None):
        db = DBSession()
        origin_name = 'Template (%s, %s)' % (imputer, estimator)
        origin_name = origin_name.replace('d3m.primitives.', '')
        pipeline = database.Pipeline(origin=origin_name, dataset=dataset)

        try:
            # TODO: Use pipeline input for this
            #count_steps = 0
            input_data = make_data_module(db, pipeline, targets, features)

            step0 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.denormalize.Common')
            count_steps = 0
            if pipeline_template:
                template_step, template_count = process_template(db, input_data, pipeline, pipeline_template)
                count_steps += template_count
                connect(db, pipeline, template_step, step0)
            else:
                connect(db, pipeline, input_data, step0, from_output='dataset')

            step1 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.dataset_to_dataframe.Common')
            connect(db, pipeline, step0, step1)
            count_steps += 1
            prev_step = step1
            if len(features_metadata['semantictypes_indices']) > 0:
                prev_step, semantic_steps = add_semantic_types(db, features_metadata, pipeline, pipeline_template, prev_step)
                count_steps += semantic_steps

            if 'ROC_AUC' in metrics[0]['metric'].name:
                step_unique = make_pipeline_module(db, pipeline, 'd3m.primitives.operator.compute_unique_values.Common')
                connect(db, pipeline, prev_step, step_unique)
                count_steps += 1
            else:
                step_unique = prev_step

            step2 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                       'column_parser.Common')
            connect(db, pipeline, step_unique, step2)
            count_steps += 1
            step3 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                       'extract_columns_by_semantic_types.Common')
            set_hyperparams(db, pipeline, step3,
                            semantic_types=['https://metadata.datadrivendiscovery.org/types/Attribute'],
                            exclude_columns=privileged_data
                            )
            connect(db, pipeline, step2, step3)
            count_steps += 1

            step4 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                       'extract_columns_by_semantic_types.Common')
            set_hyperparams(db, pipeline, step4,
                            semantic_types=['https://metadata.datadrivendiscovery.org/types/TrueTarget']
                            )
            connect(db, pipeline, step_unique, step4)
            count_steps += 1
            step5 = make_pipeline_module(db, pipeline, imputer)
            set_hyperparams(db, pipeline, step5, strategy='most_frequent')
            connect(db, pipeline, step3, step5)
            count_steps += 1
            encoder_step, encode_steps = encode_features(pipeline, step5, step4, features_metadata, db)
            other_prev_step = encoder_step
            count_steps += encode_steps
            if encoder_step == step5:  # Encoders were not applied, so use one_hot_encoder for all features
                step_fallback = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.encoder.DSBOX')
                set_hyperparams(db, pipeline, step_fallback, n_limit=50)
                connect(db, pipeline, step5, step_fallback)
                other_prev_step = step_fallback
                count_steps += 1

            step6 = make_pipeline_module(db, pipeline, estimator)
            connect(db, pipeline, other_prev_step, step6)
            connect(db, pipeline, step4, step6, to_input='outputs')
            count_steps += 1
            if 'ROC_AUC' in metrics[0]['metric'].name:
                step7 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'construct_confidence.Common')
                set_hyperparams(db, pipeline, step7,
                                primitive_learner={"type": "PRIMITIVE", "data": count_steps}
                                )
                connect(db, pipeline, step6, step7, from_output='index', to_input='index')
                connect(db, pipeline, step_unique, step7)
                connect(db, pipeline, prev_step, step7, to_input='reference')
            else:
                step7 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'construct_predictions.Common')
                connect(db, pipeline, step6, step7)
                connect(db, pipeline, prev_step, step7, to_input='reference')

            db.add(pipeline)
            db.commit()
            return pipeline.id
        except:
            logger.exception('Error creating pipeline id=%s', pipeline.id)
            return None
        finally:
            db.close()

    @staticmethod
    def make_denormalize_pipeline(dataset, targets, features, DBSession=None):
        db = DBSession()
        pipeline = database.Pipeline(origin="denormalize", dataset=dataset)

        try:
            input_data = make_data_module(db, pipeline, targets, features)

            step0 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.denormalize.Common')
            connect(db, pipeline, input_data, step0, from_output='dataset')

            step1 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.dataset_to_dataframe.Common')
            connect(db, pipeline, step0, step1)

            db.add(pipeline)
            db.commit()
            return pipeline.id
        except:
            logger.exception('Error creating pipeline id=%s', pipeline.id)
            return None
        finally:
            db.close()

    TEMPLATES = {
        'CLASSIFICATION': list(itertools.product(
            # Imputer
            ['d3m.primitives.data_cleaning.imputer.SKlearn'],
            # Classifier
            [
                'd3m.primitives.classification.random_forest.SKlearn',
                'd3m.primitives.classification.extra_trees.SKlearn',
                'd3m.primitives.classification.gradient_boosting.SKlearn',
                'd3m.primitives.classification.linear_svc.SKlearn',
                'd3m.primitives.classification.sgd.SKlearn'
            ],
        )),
        'DEBUG_CLASSIFICATION': list(itertools.product(
            # Imputer
            ['d3m.primitives.data_cleaning.imputer.SKlearn'],
            # Classifier
            [
                'd3m.primitives.classification.random_forest.SKlearn',
                'd3m.primitives.classification.extra_trees.SKlearn'
            ],
        )),
        'REGRESSION': list(itertools.product(
            # Imputer
            ['d3m.primitives.data_cleaning.imputer.SKlearn'],
            # Classifier
            [
                'd3m.primitives.regression.random_forest.SKlearn',
                'd3m.primitives.regression.extra_trees.SKlearn',
                'd3m.primitives.regression.sgd.SKlearn',
                'd3m.primitives.regression.gradient_boosting.SKlearn',
                'd3m.primitives.regression.lasso.SKlearn'
            ],
        )),
        'DEBUG_REGRESSION': list(itertools.product(
            # Imputer
            ['d3m.primitives.data_cleaning.imputer.SKlearn'],
            # Classifier
            [
                'd3m.primitives.regression.random_forest.SKlearn',
                'd3m.primitives.regression.gradient_boosting.SKlearn'
            ],
        )),
    }


class TimeseriesClassificationBuilder(BaseBuilder):

    def make_d3mpipeline(self, primitives, origin, dataset, pipeline_template, targets, features,
                         features_metadata, privileged_data=[], metrics=[], DBSession=None):
        db = DBSession()
        origin_name = '%s (%s)' % (origin, ', '.join([p.replace('d3m.primitives.', '') for p in primitives]))
        pipeline = database.Pipeline(origin=origin_name, dataset=dataset)

        try:
            if len(primitives) == 1:
                input_data = make_data_module(db, pipeline, targets, features)
                step0 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'time_series_formatter.DistilTimeSeriesFormatter')
                connect(db, pipeline, input_data, step0, from_output='dataset')

                step1 = make_pipeline_module(db, pipeline,
                                             'd3m.primitives.data_transformation.dataset_to_dataframe.Common')
                connect(db, pipeline, step0, step1)

                step2 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'dataset_to_dataframe.Common')
                connect(db, pipeline, input_data, step2, from_output='dataset')

                if 'ROC_AUC' in metrics[0]['metric'].name:
                    step_unique = make_pipeline_module(db, pipeline,
                                                       'd3m.primitives.operator.compute_unique_values.Common')
                    connect(db, pipeline, step2, step_unique)
                else:
                    step_unique = step2

                step3 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.column_parser.Common')

                set_hyperparams(db, pipeline, step3, parse_semantic_types=[
                                                      'http://schema.org/Boolean',
                                                      'http://schema.org/Integer',
                                                      'http://schema.org/Float',
                                                      'https://metadata.datadrivendiscovery.org/types/FloatVector'])
                connect(db, pipeline, step_unique, step3)

                step4 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'extract_columns_by_semantic_types.Common')
                set_hyperparams(db, pipeline, step4,
                                semantic_types=['https://metadata.datadrivendiscovery.org/types/Target',
                                                'https://metadata.datadrivendiscovery.org/types/TrueTarget',
                                                'https://metadata.datadrivendiscovery.org/types/SuggestedTarget'
                                                ]
                                )
                connect(db, pipeline, step1, step4)

                step5 = make_pipeline_module(db, pipeline, primitives[0])
                if primitives[0] == 'd3m.primitives.time_series_classification.convolutional_neural_net.LSTM_FCN':
                    set_hyperparams(db, pipeline, step5, epochs=1)
                connect(db, pipeline, step1, step5)
                connect(db, pipeline, step4, step5, to_input='outputs')

                if 'ROC_AUC' in metrics[0]['metric'].name:
                    step6 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                               'construct_confidence.Common')
                    set_hyperparams(db, pipeline, step6,
                                    primitive_learner={"type": "PRIMITIVE", "data": 6}
                                    )
                    connect(db, pipeline, step5, step6, from_output='index', to_input='index')
                    connect(db, pipeline, step_unique, step6)
                    connect(db, pipeline, step2, step6, to_input='reference')
                else:
                    step6 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                               'construct_predictions.Common')
                    connect(db, pipeline, step5, step6)
                    connect(db, pipeline, step2, step6, to_input='reference')

                db.add(pipeline)
                db.commit()
                logger.info('%s PIPELINE ID: %s', origin, pipeline.id)
                return pipeline.id
            else:
                pipeline_id = super().make_d3mpipeline(primitives, origin, dataset, pipeline_template,
                                                       targets, features, features_metadata,
                                                       privileged_data=privileged_data,
                                                       metrics=metrics, DBSession=DBSession)
                return pipeline_id
        except:
            logger.exception('Error creating pipeline id=%s, primitives=%s', pipeline.id, str(primitives))
            return None
        finally:
            db.close()


class CommunityDetectionBuilder(BaseBuilder):

    def make_d3mpipeline(self, primitives, origin, dataset, pipeline_template, targets, features,
                         features_metadata, privileged_data=[], metrics=[], DBSession=None):
        db = DBSession()
        origin_name = '%s (%s)' % (origin, ', '.join([p.replace('d3m.primitives.', '') for p in primitives]))
        pipeline = database.Pipeline(origin=origin_name, dataset=dataset)

        try:
            if len(primitives) == 1:
                input_data = make_data_module(db, pipeline, targets, features)

                step0 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'load_single_graph.DistilSingleGraphLoader')
                connect(db, pipeline, input_data, step0, from_output='dataset')

                step1 = make_pipeline_module(db, pipeline, primitives[0])
                connect(db, pipeline, step0, step1)
                connect(db, pipeline, step0, step1, to_input='outputs', from_output='produce_target')

                db.add(pipeline)
                db.commit()
                logger.info('%s PIPELINE ID: %s', origin, pipeline.id)
                return pipeline.id
            else:
                pipeline_id = super().make_d3mpipeline(primitives, origin, dataset, pipeline_template,
                                                       targets, features, features_metadata,
                                                       privileged_data=privileged_data,
                                                       metrics=metrics, DBSession=DBSession)
                return pipeline_id
        except:
            logger.exception('Error creating pipeline id=%s, primitives=%s', pipeline.id, str(primitives))
            return None
        finally:
            db.close()


class LinkPredictionBuilder(BaseBuilder):
    def make_d3mpipeline(self, primitives, origin, dataset, pipeline_template, targets, features,
                         features_metadata, privileged_data=[], metrics=[], DBSession=None):
        db = DBSession()
        origin_name = '%s (%s)' % (origin, ', '.join([p.replace('d3m.primitives.', '') for p in primitives]))
        pipeline = database.Pipeline(origin=origin_name, dataset=dataset)

        try:
            if len(primitives) == 1:
                input_data = make_data_module(db, pipeline, targets, features)

                step0 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'load_single_graph.DistilSingleGraphLoader')
                connect(db, pipeline, input_data, step0, from_output='dataset')

                step1 = make_pipeline_module(db, pipeline, primitives[0])
                set_hyperparams(db, pipeline, step1, metric='accuracy')

                connect(db, pipeline, step0, step1)
                connect(db, pipeline, step0, step1, to_input='outputs', from_output='produce_target')

                db.add(pipeline)
                db.commit()
                logger.info('%s PIPELINE ID: %s', origin, pipeline.id)
                return pipeline.id
            else:
                pipeline_id = super().make_d3mpipeline(primitives, origin, dataset, pipeline_template,
                                                       targets, features, features_metadata,
                                                       privileged_data=privileged_data,
                                                       metrics=metrics, DBSession=DBSession)
                return pipeline_id
        except:
            logger.exception('Error creating pipeline id=%s, primitives=%s', pipeline.id, str(primitives))
            return None
        finally:
            db.close()


class GraphMatchingBuilder(BaseBuilder):
    def make_d3mpipeline(self, primitives, origin, dataset, pipeline_template, targets, features,
                         features_metadata, privileged_data=[], metrics=[], DBSession=None):
        db = DBSession()
        origin_name = '%s (%s)' % (origin, ', '.join([p.replace('d3m.primitives.', '') for p in primitives]))
        try:
            if len(primitives) == 1:
                origin_name = 'MtLDB ' + origin_name
                pipeline = database.Pipeline(origin=origin_name, dataset=dataset)

                input_data = make_data_module(db, pipeline, targets, features)

                step0 = make_pipeline_module(db, pipeline, primitives[0])
                connect(db, pipeline, input_data, step0)

                db.add(pipeline)
                db.commit()
                logger.info('%s PIPELINE ID: %s', origin, pipeline.id)
                return pipeline.id
            else:
                pipeline = database.Pipeline(origin=origin_name, dataset=dataset)
                pipeline_id = super().make_d3mpipeline(primitives, origin, dataset, pipeline_template,
                                                       targets, features, features_metadata,
                                                       privileged_data=privileged_data,
                                                       metrics=metrics, DBSession=DBSession)
                return pipeline_id
        except:
            logger.exception('Error creating pipeline id=%s, primitives=%s', pipeline.id, str(primitives))
            return None
        finally:
            db.close()


class VertexClassificationBuilder(BaseBuilder):
    def make_d3mpipeline(self, primitives, origin, dataset, pipeline_template, targets, features,
                         features_metadata, privileged_data=[], metrics=[], DBSession=None):
        db = DBSession()
        origin_name = '%s (%s)' % (origin, ', '.join([p.replace('d3m.primitives.', '') for p in primitives]))
        pipeline = database.Pipeline(origin=origin_name, dataset=dataset)

        try:
            if len(primitives) == 1 and primitives[0] == 'd3m.primitives.classification.gaussian_classification.JHU':
                input_data = make_data_module(db, pipeline, targets, features)

                step0 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.load_graphs.JHU')
                connect(db, pipeline, input_data, step0, from_output='dataset')

                step1 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_preprocessing.largest_connected_component.JHU')
                connect(db, pipeline, step0, step1)

                step2 = make_pipeline_module(db, pipeline,
                                             'd3m.primitives.data_transformation.adjacency_spectral_embedding.JHU')
                set_hyperparams(db, pipeline, step2, max_dimension=5, use_attributes=True)
                connect(db, pipeline, step1, step2)

                step3 = make_pipeline_module(db, pipeline,
                                             'd3m.primitives.classification.gaussian_classification.JHU')
                connect(db, pipeline, step2, step3)

                db.add(pipeline)
                db.commit()
                logger.info('%s PIPELINE ID: %s', origin, pipeline.id)
                return pipeline.id

            elif len(primitives) == 1 and primitives[0] == 'd3m.primitives.vertex_nomination.seeded_graph_matching.DistilVertexNomination':
                input_data = make_data_module(db, pipeline, targets, features)

                step0 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.load_edgelist.DistilEdgeListLoader')
                connect(db, pipeline, input_data, step0, from_output='dataset')

                step1 = make_pipeline_module(db, pipeline, primitives[0])
                set_hyperparams(db, pipeline, step1, metric='accuracy')
                connect(db, pipeline, step0, step1)
                connect(db, pipeline, step0, step1, to_input='outputs', from_output='produce_target')

                db.add(pipeline)
                db.commit()
                logger.info('%s PIPELINE ID: %s', origin, pipeline.id)
                return pipeline.id
            else:
                pipeline_id = super().make_d3mpipeline(primitives, origin, dataset, pipeline_template,
                                                       targets, features, features_metadata,
                                                       privileged_data=privileged_data,
                                                       metrics=metrics, DBSession=DBSession)
                return pipeline_id
        except:
            logger.exception('Error creating pipeline id=%s, primitives=%s', pipeline.id, str(primitives))
            return None
        finally:
            db.close()


class ObjectDetectionBuilder(BaseBuilder):

    def make_d3mpipeline(self, primitives, origin, dataset, pipeline_template, targets, features,
                         features_metadata, privileged_data=[], metrics=[], DBSession=None):
        db = DBSession()
        origin_name = '%s (%s)' % (origin, ', '.join([p.replace('d3m.primitives.', '') for p in primitives]))
        pipeline = database.Pipeline(origin=origin_name, dataset=dataset)

        try:
            input_data = make_data_module(db, pipeline, targets, features)

            step0 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.denormalize.Common')
            connect(db, pipeline, input_data, step0, from_output='dataset')

            if primitives[0] == 'd3m.primitives.feature_extraction.yolo.DSBOX':
                step1 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'dataset_to_dataframe.Common')
                connect(db, pipeline, step0, step1)
                if 'ROC_AUC' in metrics[0]['metric'].name:
                    step_unique = make_pipeline_module(db, pipeline,
                                                       'd3m.primitives.operator.compute_unique_values.Common')
                    connect(db, pipeline, step1, step_unique)

                else:
                    step_unique = step1
                step2 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'extract_columns_by_semantic_types.Common')
                set_hyperparams(db, pipeline, step2,
                                semantic_types=['https://metadata.datadrivendiscovery.org/types/PrimaryMultiKey',
                                                'https://metadata.datadrivendiscovery.org/types/FileName']
                                )
                connect(db, pipeline, step_unique, step2)

                step3 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'extract_columns_by_semantic_types.Common')
                set_hyperparams(db, pipeline, step3,
                                semantic_types=['https://metadata.datadrivendiscovery.org/types/TrueTarget'],
                                )
                connect(db, pipeline, step1, step3)

                step4 = make_pipeline_module(db, pipeline, primitives[0])
                connect(db, pipeline, step2, step4)
                connect(db, pipeline, step3, step4, to_input='outputs')

                if 'ROC_AUC' in metrics[0]['metric'].name:
                    step5 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                               'construct_confidence.Common')
                    set_hyperparams(db, pipeline, step5,
                                    primitive_learner={"type": "PRIMITIVE", "data": 4}
                                    )
                    connect(db, pipeline, step4, step5, from_output='index', to_input='index')
                    connect(db, pipeline, step_unique, step5)
                    connect(db, pipeline, step2, step5, to_input='reference')
                else:
                    step5 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'construct_predictions.Common')
                    connect(db, pipeline, step4, step5)
                    connect(db, pipeline, step2, step5, to_input='reference')
            else:
                step1 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'dataset_to_dataframe.Common')
                set_hyperparams(db, pipeline, step1)
                connect(db, pipeline, step0, step1)

                step2 = make_pipeline_module(db, pipeline, primitives[0])
                connect(db, pipeline, step1, step2)
                connect(db, pipeline, step1, step2, to_input='outputs')

            db.add(pipeline)
            db.commit()
            logger.info('%s PIPELINE ID: %s', origin, pipeline.id)
            return pipeline.id
        except:
            logger.exception('Error creating pipeline id=%s, primitives=%s', pipeline.id, str(primitives))
            return None
        finally:
            db.close()


class AudioBuilder(BaseBuilder):

    def make_d3mpipeline(self, primitives, origin, dataset, pipeline_template, targets, features,
                         features_metadata, privileged_data=[], metrics=[], DBSession=None):
        db = DBSession()
        origin_name = '%s (%s)' % (origin, ', '.join([p.replace('d3m.primitives.', '') for p in primitives]))
        pipeline = database.Pipeline(origin=origin_name, dataset=dataset)

        try:
            input_data = make_data_module(db, pipeline, targets, features)

            step0 = make_pipeline_module(db, pipeline,
                                         'd3m.primitives.data_transformation.audio_reader.DistilAudioDatasetLoader')
            connect(db, pipeline, input_data, step0, from_output='dataset')
            if 'ROC_AUC' in metrics[0]['metric'].name:
                step_unique = make_pipeline_module(db, pipeline,
                                                   'd3m.primitives.operator.compute_unique_values.Common')
                connect(db, pipeline, step0, step_unique)

            else:
                step_unique = step0
            step1 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.column_parser.Common')
            set_hyperparams(db, pipeline, step1, parse_semantic_types=[
                        "http://schema.org/Boolean",
                        "http://schema.org/Integer",
                        "http://schema.org/Float",
                        "https://metadata.datadrivendiscovery.org/types/FloatVector"
                    ]
            )
            db.add(database.PipelineConnection(pipeline=pipeline,
                                               from_module=step_unique,
                                               to_module=step1,
                                               from_output_name='produce',
                                               to_input_name='inputs'))

            step2 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                       'extract_columns_by_semantic_types.Common')
            set_hyperparams(db, pipeline, step2,
                            semantic_types=['https://metadata.datadrivendiscovery.org/types/TrueTarget']
                            )
            connect(db, pipeline, step_unique, step2)

            step3 = make_pipeline_module(db, pipeline, primitives[0])
            db.add(database.PipelineConnection(pipeline=pipeline,
                                               from_module=step_unique,
                                               to_module=step3,
                                               from_output_name='produce_collection',
                                               to_input_name='inputs'))

            step = prev_step = step3
            preprocessors = primitives[1:-1]
            estimator = primitives[-1]

            for preprocessor in preprocessors:
                step = make_pipeline_module(db, pipeline, preprocessor)
                change_default_hyperparams(db, pipeline, preprocessor, step)
                connect(db, pipeline, prev_step, step)
                prev_step = step

                to_module_primitive = index.get_primitive(preprocessor)
                if 'outputs' in to_module_primitive.metadata.query()['primitive_code']['arguments']:
                    connect(db, pipeline, step2, step, to_input='outputs')

            step5 = make_pipeline_module(db, pipeline, estimator)
            change_default_hyperparams(db, pipeline, estimator, step5)
            connect(db, pipeline, step, step5)
            connect(db, pipeline, step2, step5, to_input='outputs')

            if 'ROC_AUC' in metrics[0]['metric'].name:
                count_steps = 4 + len(primitives)
                step6 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'construct_confidence.Common')
                set_hyperparams(db, pipeline, step6,
                                primitive_learner={"type": "PRIMITIVE", "data": count_steps}
                                )
                connect(db, pipeline, step5, step6, from_output='index', to_input='index')
                connect(db, pipeline, step_unique, step6)
                connect(db, pipeline, step1, step6, to_input='reference')
            else:
                step6 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'construct_predictions.Common')
                connect(db, pipeline, step5, step6)
                connect(db, pipeline, step1, step6, to_input='reference')

            db.add(pipeline)
            db.commit()

            db.add(pipeline)
            db.commit()
            logger.info('%s PIPELINE ID: %s', origin, pipeline.id)
            return pipeline.id
        except:
            logger.exception('Error creating pipeline id=%s, primitives=%s', pipeline.id, str(primitives))
            return None
        finally:
            db.close()


class SemisupervisedClassificationBuilder(BaseBuilder):

    def make_d3mpipeline(self, primitives, origin, dataset, pipeline_template, targets, features,
                         features_metadata, privileged_data=[], metrics=[], DBSession=None):
        db = DBSession()
        origin_name = '%s (%s)' % (origin, ', '.join([p.replace('d3m.primitives.', '') for p in primitives]))
        pipeline = database.Pipeline(origin=origin_name, dataset=dataset)

        try:
            if 'semisupervised_classification.iterative_labeling.AutonBox' in primitives[-1]:

                input_data = make_data_module(db, pipeline, targets, features)
                step0 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.denormalize.Common')
                count_steps = 0
                if pipeline_template:
                    template_step, template_steps = process_template(db, input_data, pipeline, pipeline_template)
                    connect(db, pipeline, template_step, step0)
                    count_steps += template_steps
                else:
                    connect(db, pipeline, input_data, step0, from_output='dataset')

                step1 = make_pipeline_module(db, pipeline,
                                             'd3m.primitives.data_transformation.dataset_to_dataframe.Common')

                count_steps += 1
                connect(db, pipeline, step0, step1)

                prev_step = step1
                if len(features_metadata['semantictypes_indices']) > 0:
                    prev_step, semantic_steps_count = add_semantic_types(db, features_metadata, pipeline,
                                                                   pipeline_template, prev_step)
                    count_steps += semantic_steps_count
                if 'ROC_AUC' in metrics[0]['metric'].name:
                    step_unique = make_pipeline_module(db, pipeline,
                                                       'd3m.primitives.operator.compute_unique_values.Common')
                    connect(db, pipeline, prev_step, step_unique)
                    count_steps += 1
                else:
                    step_unique = prev_step
                step2 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'column_parser.Common')
                count_steps += 1
                connect(db, pipeline, prev_step, step2)

                step3 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'extract_columns_by_semantic_types.Common')
                count_steps += 1

                set_hyperparams(db, pipeline, step3,
                                semantic_types=['https://metadata.datadrivendiscovery.org/types/Attribute'],
                                exclude_columns=privileged_data)
                connect(db, pipeline, step2, step3)

                step4 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                           'extract_columns_by_semantic_types.Common')
                count_steps += 1
                set_hyperparams(db, pipeline, step4,
                                semantic_types=['https://metadata.datadrivendiscovery.org/types/TrueTarget']
                                )
                connect(db, pipeline, prev_step, step4)

                step = otherprev_step = step3
                preprocessors = primitives[:-2]
                blackbox = primitives[-2]
                estimator = primitives[-1]

                for preprocessor in preprocessors:
                    step = make_pipeline_module(db, pipeline, preprocessor)
                    count_steps += 1
                    change_default_hyperparams(db, pipeline, preprocessor, step)
                    connect(db, pipeline, otherprev_step, step)
                    otherprev_step = step

                    to_module_primitive = index.get_primitive(preprocessor)
                    if 'outputs' in to_module_primitive.metadata.query()['primitive_code']['arguments']:
                        connect(db, pipeline, step4, step, to_input='outputs')

                step_blackbox = make_pipeline_module(db, pipeline, blackbox)
                count_steps += 1
                change_default_hyperparams(db, pipeline, blackbox, step_blackbox)
                connect(db, pipeline, step, step_blackbox)
                connect(db, pipeline, step4, step_blackbox, to_input='outputs')


                step5 = make_pipeline_module(db, pipeline, estimator)
                change_default_hyperparams(db, pipeline, estimator, step5)
                connect(db, pipeline, step_blackbox, step5,from_output='index', to_input='index')
                connect(db, pipeline, step, step5)
                set_hyperparams(db, pipeline, step5,
                                blackbox={ "type": "PRIMITIVE", "data": count_steps }
                                )
                count_steps += 1
                to_module_primitive = index.get_primitive(estimator)
                if 'outputs' in to_module_primitive.metadata.query()['primitive_code']['arguments']:
                    connect(db, pipeline, step4, step5, to_input='outputs')

                if 'ROC_AUC' in metrics[0]['metric'].name:
                    step6 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                               'construct_confidence.Common')
                    set_hyperparams(db, pipeline, step6,
                                    primitive_learner={"type": "PRIMITIVE", "data": count_steps}
                                    )
                    connect(db, pipeline, step5, step6, from_output='index', to_input='index')
                    connect(db, pipeline, step_unique, step6)
                    connect(db, pipeline, prev_step, step6, to_input='reference')
                else:
                    step6 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                               'construct_predictions.Common')
                    connect(db, pipeline, step5, step6)
                    connect(db, pipeline, prev_step, step6, to_input='reference')

                db.add(pipeline)
                db.commit()
                logger.info('%s PIPELINE ID: %s', origin, pipeline.id)
                return pipeline.id
            else:
                pipeline_id = super().make_d3mpipeline(primitives, origin, dataset, pipeline_template,
                                                       targets, features, features_metadata,
                                                       privileged_data=privileged_data,
                                                       metrics=metrics, DBSession=DBSession)
                return pipeline_id
        except:
            logger.exception('Error creating pipeline id=%s, primitives=%s', pipeline.id, str(primitives))
            return None
        finally:
            db.close()


class CollaborativeFilteringBuilder:

    def make_d3mpipeline(self, primitives, origin, dataset, pipeline_template, targets, features,
                         features_metadata, privileged_data=[], metrics=[], DBSession=None):
        # TODO parameters 'features and 'targets' are not needed
        db = DBSession()
        dataset_path = dataset[7:]
        origin_name = '%s (%s)' % (origin, ', '.join([p.replace('d3m.primitives.', '') for p in primitives]))
        pipeline = database.Pipeline(origin=origin_name, dataset=dataset)

        try:
            input_data = make_data_module(db, pipeline, targets, features)

            step0 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.denormalize.Common')
            if pipeline_template:
                template_step, _ = process_template(db, input_data, pipeline, pipeline_template)
                connect(db, pipeline, template_step, step0)
            else:
                connect(db, pipeline, input_data, step0, from_output='dataset')

            step1 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.dataset_to_dataframe.Common')
            connect(db, pipeline, step0, step1)

            prev_step = step1
            if is_collection(dataset_path):
                prev_step = add_file_readers(db, pipeline, prev_step, dataset_path)

            if len(features_metadata['semantictypes_indices']) > 0:
                prev_step, _ = add_semantic_types(db, features_metadata, pipeline, pipeline_template, prev_step)

            dataframe_step = prev_step
            if need_entire_dataframe(primitives):
                prev_step, primitives = add_previous_primitive(db, pipeline, primitives, prev_step)

            step2 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.column_parser.Common')
            connect(db, pipeline, prev_step, step2)

            step3 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                       'extract_columns_by_semantic_types.Common')
            set_hyperparams(db, pipeline, step3,
                            semantic_types=['https://metadata.datadrivendiscovery.org/types/Attribute'],
                            exclude_columns=privileged_data)
            connect(db, pipeline, step2, step3)

            step4 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                       'extract_columns_by_semantic_types.Common')
            set_hyperparams(db, pipeline, step4,
                            semantic_types=['https://metadata.datadrivendiscovery.org/types/TrueTarget'])
            connect(db, pipeline, step2, step4)
            # TODO: Remove this class, it's needed just to perform column_parser in targets, see above

            current_step = prev_step = step3

            for primitive in primitives:
                current_step = make_pipeline_module(db, pipeline, primitive)
                change_default_hyperparams(db, pipeline, primitive, current_step)
                connect(db, pipeline, prev_step, current_step)
                prev_step = current_step

                to_module_primitive = index.get_primitive(primitive)
                if 'outputs' in to_module_primitive.metadata.query()['primitive_code']['arguments']:
                    connect(db, pipeline, step4, current_step, to_input='outputs')

            step5 = make_pipeline_module(db, pipeline, 'd3m.primitives.data_transformation.'
                                                       'construct_predictions.Common')
            connect(db, pipeline, current_step, step5)
            connect(db, pipeline, dataframe_step, step5, to_input='reference')

            db.add(pipeline)
            db.commit()
            logger.info('%s PIPELINE ID: %s', origin, pipeline.id)
            return pipeline.id
        except:
            logger.exception('Error creating pipeline id=%s, primitives=%s', pipeline.id, str(primitives))
            return None
        finally:
            db.close()
