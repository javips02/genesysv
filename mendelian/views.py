import csv
import json
import pprint
from datetime import datetime

from django.core import serializers
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import (HttpResponse, HttpResponseForbidden,
                         HttpResponseServerError, JsonResponse, QueryDict,
                         StreamingHttpResponse)
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.generic.base import TemplateView

import complex.views as complex_views
import core.models as core_models
from common.utils import Echo
from core.forms import (AnalysisTypeForm, AttributeForm, AttributeFormPart,
                        DatasetForm, FilterForm, FilterFormPart,
                        SaveSearchForm, StudyForm)
from core.models import Dataset, Study
from core.utils import BaseSearchElasticsearch, get_values_from_es
from core.views import AppHomeView, BaseSearchView
from mendelian.forms import FamilyForm, KindredForm, MendelianAnalysisForm
from mendelian.utils import (MendelianElasticSearchQueryExecutor,
                             MendelianElasticsearchResponseParser,
                             MendelianSearchElasticsearch)


class MendelianHomeView(AppHomeView):
    template_name = "mendelian/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        study_obj = get_object_or_404(Study, pk=self.kwargs.get('study_id'))
        context['study_obj'] = get_object_or_404(
            Study, pk=self.kwargs.get('study_id'))
        context['dataset_form'] = DatasetForm(study_obj, self.request.user)
        context['mendelian_analysis_form'] = MendelianAnalysisForm()
        return context


class KindredSnippetView(View):
    form_class = KindredForm
    template_name = "mendelian/kindred_form_template.html"

    def generate_kindred_form(self, dataset_obj):
        family_ids = get_values_from_es(dataset_obj.es_index_name,
                                        dataset_obj.es_host,
                                        dataset_obj.es_port,
                                        'Family_ID',
                                        'sample')
        number_of_families = len(family_ids)
        kindred_form = self.form_class(number_of_families)

        return kindred_form

    def get_kindred_form_response(self, request, dataset_obj):
        cache_name = 'kindred_form_for_{}'.format(dataset_obj.id)
        cached_form = cache.get(cache_name)
        if cached_form:
            return cached_form
        else:
            kindred_form = self.generate_kindred_form(dataset_obj)
            context = {}
            context['kindred_form'] = kindred_form
            response = render(
                request, self.template_name, context)
            cache.set(cache_name, response, None)
            return response

    def get(self, request, *args, **kwargs):
        dataset_obj = get_object_or_404(
            Dataset, pk=kwargs.get('dataset_id'))
        kindred_form_response = self.get_kindred_form_response(
            request, dataset_obj)
        return kindred_form_response


class FamilySnippetView(View):
    form_class = FamilyForm
    template_name = "mendelian/family_form_template.html"

    def generate_family_form(self, dataset_obj):
        sample_ids = get_values_from_es(dataset_obj.es_index_name,
                                        dataset_obj.es_host,
                                        dataset_obj.es_port,
                                        'sample_ID',
                                        'sample')
        family_form = self.form_class(sample_ids)

        return family_form

    def get_family_form_response(self, request, dataset_obj):
        cache_name = 'family_form_for_{}'.format(dataset_obj.id)
        cached_form = cache.get(cache_name)
        if cached_form:
            return cached_form
        else:
            family_form = self.generate_family_form(dataset_obj)
            context = {}
            context['family_form'] = family_form
            response = render(
                request, self.template_name, context)
            cache.set(cache_name, response, None)
            return response

    def get(self, request, *args, **kwargs):
        dataset_obj = get_object_or_404(
            Dataset, pk=kwargs.get('dataset_id'))
        family_form_response = self.get_family_form_response(
            request, dataset_obj)
        return family_form_response


class MendelianSearchView(BaseSearchView):
    search_elasticsearch_class = MendelianSearchElasticsearch
    elasticsearch_query_executor_class = MendelianElasticSearchQueryExecutor
    elasticsearch_response_parser_class = MendelianElasticsearchResponseParser
    additional_information = {}

    def validate_additional_forms(self, request, POST_data):
        family_ids = get_values_from_es(self.dataset_obj.es_index_name,
                                        self.dataset_obj.es_host,
                                        self.dataset_obj.es_port,
                                        'Family_ID',
                                        'sample')
        number_of_families = len(family_ids)

        kindred_form = KindredForm(number_of_families, POST_data)
        if kindred_form.is_valid():
            if kindred_form.cleaned_data['number_of_kindred']:
                self.additional_information = {'number_of_kindred': kindred_form.cleaned_data['number_of_kindred']}
        else:
            raise ValidationError('Invalid Kindred form!')

    def get_kwargs(self, request):
        kwargs = super().get_kwargs(request)
        if self.additional_information:
            kwargs.update(self.additional_information)
        kwargs.update({'mendelian_analysis_type': self.analysis_type_obj.name})
        return kwargs

    def post(self, request, *args, **kwargs):
        self.start_time = datetime.now()

        # Get all FORM POST Data
        POST_data = QueryDict(request.POST['form_data'])
        self.validate_request_data(request, POST_data)
        self.validate_additional_forms(request, POST_data)

        kwargs = self.get_kwargs(request)

        search_elasticsearch_obj = self.search_elasticsearch_class(**kwargs)
        search_elasticsearch_obj.search()
        header = search_elasticsearch_obj.get_header()
        results = search_elasticsearch_obj.get_results()
        elasticsearch_response_time = search_elasticsearch_obj.get_elasticsearch_response_time()
        search_log_id = search_elasticsearch_obj.get_search_log_id()
        filters_used = search_elasticsearch_obj.get_filters_used()
        attributes_selected = search_elasticsearch_obj.get_attributes_selected()

        if request.user.is_authenticated:
            save_search_form = SaveSearchForm(request.user,
                                              self.dataset_obj,
                                              self.analysis_type_obj,
                                              json.dumps(self.additional_information),
                                              filters_used,
                                              attributes_selected)
        else:
            save_search_form = None

        if self.call_get_context and request.user.is_authenticated:
            kwargs.update({'user_obj': request.user})
            kwargs.update({'search_log_obj': core_models.SearchLog.objects.get(id=search_log_id)})
            context = self.get_context_data(**kwargs)
        else:
            context = {}

        context['header'] = header
        context['results'] = results
        context['total_time'] = int((datetime.now() - self.start_time).total_seconds() * 1000)
        context['elasticsearch_response_time'] = elasticsearch_response_time
        context['search_log_id'] = search_log_id
        context['save_search_form'] = save_search_form
        context['app_name'] = self.analysis_type_obj.app_name.name
        return render(request, self.template_name, context)


class MendelianDocumentView(complex_views.ComplexDocumentView):
    pass


class MendelianDownloadView(BaseSearchView):
    search_elasticsearch_class = MendelianSearchElasticsearch
    elasticsearch_query_executor_class = MendelianElasticSearchQueryExecutor
    elasticsearch_response_parser_class = MendelianElasticsearchResponseParser

    def __init__(self):
        self.search_log_obj = None
        self.header = None
        self.results = None

    def get_kwargs(self, request):

        if self.search_log_obj.nested_attribute_fields:
            nested_attribute_fields = json.loads(self.search_log_obj.nested_attribute_fields)
        else:
            nested_attribute_fields = []

        if self.search_log_obj.non_nested_attribute_fields:
            non_nested_attribute_fields = json.loads(self.search_log_obj.non_nested_attribute_fields)
        else:
            non_nested_attribute_fields.non_nested_attribute_fields = []

        if self.search_log_obj.additional_information:
            additional_information = json.loads(self.search_log_obj.additional_information)
        else:
            additional_information = None

        if self.search_log_obj.nested_attributes_selected:
            nested_attributes_selected = json.loads(self.search_log_obj.nested_attributes_selected)
        else:
            nested_attributes_selected = None

        kwargs = {
            'user': request.user,
            'dataset_obj': self.search_log_obj.dataset,
            'analysis_type_obj': self.search_log_obj.analysis_type,
            'header': [ele.object for ele in serializers.deserialize("json", self.search_log_obj.header)],
            'query_body': json.loads(self.search_log_obj.query),
            'nested_attribute_fields': nested_attribute_fields,
            'non_nested_attribute_fields': non_nested_attribute_fields,
            'nested_attributes_selected': nested_attributes_selected,
            'elasticsearch_dsl_class': self.elasticsearch_dsl_class,
            'elasticsearch_query_executor_class': self.elasticsearch_query_executor_class,
            'elasticsearch_response_parser_class': self.elasticsearch_response_parser_class,
            'limit_results': False
        }

        if additional_information:
            kwargs.update(additional_information)
        kwargs.update({'mendelian_analysis_type': self.search_log_obj.analysis_type.name})
        return kwargs

    def generate_row(self, header, tmp_source):
        tmp = []
        for ele in header:
            tmp.append(str(tmp_source.get(ele.es_name, None)))

        return tmp

    def yield_rows(self):
        header_keys = [ele.display_text for ele in self.header]
        yield header_keys

        for idx, result in enumerate(self.results):
            row = self.generate_row(self.header, result)
            yield row

    def get(self, request, *args, **kwargs):
        self.search_log_obj = get_object_or_404(core_models.SearchLog, pk=kwargs.get('search_log_id'))


        if self.search_log_obj.user and request.user != self.search_log_obj.user:
            return HttpResponseForbidden()

        kwargs = self.get_kwargs(request)

        search_elasticsearch_obj = self.search_elasticsearch_class(**kwargs)
        search_elasticsearch_obj.download()
        self.header = search_elasticsearch_obj.get_header()
        self.results = search_elasticsearch_obj.get_results()
        rows = self.yield_rows()
        pseudo_buffer = Echo()
        writer = csv.writer(pseudo_buffer)
        response = StreamingHttpResponse((writer.writerow(row) for row in rows), content_type="text/csv")
        response['Content-Disposition'] = 'attachment; filename="search_results.csv"'

        return response
