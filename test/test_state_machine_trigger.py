# Copyright Amazon.com and its affiliates; all rights reserved. This file is Amazon Web Services Content and may not be duplicated or distributed without permission.
# SPDX-License-Identifier: MIT-0
import pytest
from moto import mock_dynamodb
import boto3
import botocore
import logging

from test.boto_mocking_helper import *
import lib.state_machine_trigger.lambda_handler as lambda_handler

test_table_name = 'test-etl-job-audit'
test_state_machine_name = 'test-state-machine'
test_state_machine_arn = f'arn:aws:states:{mock_region}:{mock_account_id}:stateMachine:{test_state_machine_name}'
test_bucket_arn = 'arn:aws:s3:::test-bucket'
test_execution_id = '3b278a83-8b04-468a-983e-3749b6609dcb'
test_event_time = '2023-01-01T23:30:00.000Z'

test_success_event = {
    'Records': [{
        'eventTime': test_event_time, 
        's3': {
            'bucket': { 'name': 'test-bucket', 'arn': test_bucket_arn }, 
            'object': { 'key': 'level1/level2/test-file.csv' }
        },
        'userIdentity': { 'principalId': 'testuser' },
        'requestParameters': { 'sourceIPAddress': 'testipaddress'},
    }]
}

test_bad_file_path_event1 = {
    'Records': [{
        'eventTime': test_event_time, 
        's3': {
            'bucket': { 'name': 'test-bucket', 'arn': test_bucket_arn }, 
            'object': { 'key': 'top-level-test-file.csv' }
        },
        'userIdentity': { 'principalId': 'testuser' },
        'requestParameters': { 'sourceIPAddress': 'testipaddress'},
    }]
}

test_bad_file_path_event2 = {
    'Records': [{
        'eventTime': test_event_time, 
        's3': {
            'bucket': { 'name': 'test-bucket', 'arn': test_bucket_arn }, 
            'object': { 'key': 'test-source-system/first-level-test-file.csv' }
        },
        'userIdentity': { 'principalId': 'testuser' },
        'requestParameters': { 'sourceIPAddress': 'testipaddress'},
    }]
}

test_bad_folder_event = {
    'Records': [{
        'eventTime': test_event_time, 
        's3': {
            'bucket': { 'name': 'test-bucket', 'arn': test_bucket_arn }, 
            'object': { 'key': 'level1/level2/' }
        },
        'userIdentity': { 'principalId': 'testuser' },
        'requestParameters': { 'sourceIPAddress': 'testipaddress'},
    }]
}

test_context = {
    'aws_request_id': 'd7d36c0e-a1bc-11ed-a8fc-0242ac120002',
    'function_name': 'testfunction',
    'invoked_function_arn': 'arn:aws:lambda:::function:notrealarn',
    'identity': None,
    'client_context': None
}


def mock_record_etl_job_run(audit_table_name: str, sfn_arn: str, execution_id: str,
        execution_name: str, execution_input: str, principal_id: str, source_ipaddress: str):
    # Mock function does not need to do any work
    pass


@pytest.fixture
def use_moto():
    @mock_dynamodb
    def dynamodb_client_and_audit_table():
        dynamodb = boto3.resource('dynamodb')
 
        # KeySchema, AttributeDefinitions, and BillingMode should match
        # dynamodb table creation in dynamodb_stack
        table = dynamodb.create_table(
            TableName=test_table_name,
            KeySchema=[
                { 'AttributeName': 'execution_id', 'KeyType': 'HASH' }
            ],
            AttributeDefinitions=[
                { 'AttributeName': 'execution_id', 'AttributeType': 'S' }
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        return table
    return dynamodb_client_and_audit_table


def test_handler_success_returns_200(monkeypatch):
    monkeypatch.setattr(lambda_handler.boto3, 'client', mock_boto3_client)
    monkeypatch.setattr(lambda_handler, 'record_etl_job_run', mock_record_etl_job_run)
    monkeypatch.setenv('DYNAMODB_TABLE_NAME', test_table_name)
    monkeypatch.setenv('SFN_STATE_MACHINE_ARN', test_state_machine_arn)

    result = lambda_handler.lambda_handler(test_success_event, test_context)
    assert result['statusCode'] == 200


def test_handler_bad_file_returns_400(monkeypatch):
    monkeypatch.setattr(lambda_handler.boto3, 'client', mock_boto3_client)
    monkeypatch.setattr(lambda_handler, 'record_etl_job_run', mock_record_etl_job_run)
    monkeypatch.setenv('DYNAMODB_TABLE_NAME', test_table_name)
    monkeypatch.setenv('SFN_STATE_MACHINE_ARN', test_state_machine_arn)

    result1 = lambda_handler.lambda_handler(test_bad_file_path_event1, test_context)
    assert result1['statusCode'] == 400

    result2 = lambda_handler.lambda_handler(test_bad_file_path_event2, test_context)
    assert result2['statusCode'] == 400



def test_handler_folder_putobject_returns_400(monkeypatch):
    monkeypatch.setattr(lambda_handler.boto3, 'client', mock_boto3_client)
    monkeypatch.setattr(lambda_handler, 'record_etl_job_run', mock_record_etl_job_run)
    monkeypatch.setenv('DYNAMODB_TABLE_NAME', test_table_name)
    monkeypatch.setenv('SFN_STATE_MACHINE_ARN', test_state_machine_arn)

    result = lambda_handler.lambda_handler(test_bad_folder_event, test_context)
    assert result['statusCode'] == 400


@mock_dynamodb
def test_record_etl_job_run_records_status(monkeypatch, use_moto):
    monkeypatch.setenv('AWS_DEFAULT_REGION', mock_region)
    table = use_moto()

    lambda_handler.record_etl_job_run(test_table_name, test_state_machine_arn, test_execution_id, 'test-execution', '{}', 'testUser', 'testipaddress')

    item = table.get_item(
        TableName=test_table_name,
        Key={ 'execution_id': test_execution_id }
    )
    assert item['Item']['job_latest_status'] == 'STARTED'


@mock_dynamodb
def test_record_etl_jon_run_logs_no_table(monkeypatch, caplog):
    monkeypatch.setenv('AWS_DEFAULT_REGION', mock_region)
    # Purposely do not call use_moto() to create the table

    with pytest.raises(botocore.exceptions.ClientError) as e_info:
        lambda_handler.record_etl_job_run(test_table_name, test_state_machine_arn, test_execution_id, 'test-execution', '{}', 'testUser', 'testipaddress')

    assert e_info.match('ResourceNotFoundException'), 'Expected Boto3 Client Error not raised'

    with caplog.at_level(logging.ERROR):
        assert caplog.text.find('Requested resource not found') != -1