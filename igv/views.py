from django.shortcuts import render, redirect
from django.http import HttpResponse
from search.models import Dataset
import elasticsearch
from search.utils import get_es_result
from pybamview.forms import SampleSelectForm
from pybamview.models import SampleBamInfo
from django.conf import settings

def get_sample_ids(result):
    return sorted([(ele['sample_ID']) for ele in result['sample']])

def igvview(request):
    if request.POST:
        if 'igvredirect' in request.POST:
            dataset_id = request.POST.get('dataset_id')
            Chr = request.POST.get('Chr')
            Start = int(request.POST.get('Start'))
            dataset = Dataset.objects.get(id=dataset_id)

            try:
                locus = '"chr%s:%d-%d"' %(Chr, Start-50, Start+50)
                bam_files = []
                for sample in (key for key,val in request.POST.items() if 'on' in val):
                    sample_bam_info_obj = SampleBamInfo.objects.get(dataset=dataset, sample_id=sample)
                    url = sample_file=sample_bam_info_obj.file_path.replace('/gpfs/projects/academic/big/','http://199.109.192.189/' )
                    name = sample
                    tmp = {'url': url, 'name': name}
                    bam_files.append(tmp)
                context = {}
                context['bam_files'] = bam_files
                context['locus'] = locus
                return render(request, "igv/igv_lite.html", context)
                # for sample in (key for key,val in request.POST.items() if 'on' in val):
                #     sample_bam_info_obj = SampleBamInfo.objects.get(dataset=dataset, sample_id=sample)
                #     url_string += 'samplebams={sample_name}:{sample_file}&'.format(sample_name=sample_bam_info_obj.sample_id,
                #                                                                    sample_file=sample_bam_info_obj.file_path)

                # url_string += 'zoomlevel=1'
                # url_string += '&region=%d:%d' %(Chr,Start)
                # return redirect(url_string)
                # # return redirect(url_string)
            except:
                return HttpResponse('Missing BAM file for: %s' %(sample))


        else:
            dataset_id = request.POST.get('dataset_id')
            dataset = Dataset.objects.get(id=dataset_id)
            variant_id = request.POST.get('variant_id')
            index_name = request.POST.get('index_name')
            type_name = request.POST.get('type_name')
            es = elasticsearch.Elasticsearch(host=dataset.es_host)
            result = get_es_result(es, index_name, type_name, variant_id)
            sample_ids = get_sample_ids(result)

            sample_select_form = SampleSelectForm(sample_ids)
            context = {}
            context['Variant'] = result['Variant']
            context['dataset_id'] = dataset_id
            context['variant_id'] = variant_id
            context['Chr'] = result['Chr']
            context['Start'] = result['Start']
            context['sample_ids'] = sample_ids
            context['sample_select_form'] = sample_select_form
            return render(request, 'igv/igvview.html', context)
            # return HttpResponse(result)

    else:
        return HttpResponse('What Happened!')
