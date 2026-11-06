from django.core.management.base import BaseCommand
from django.utils import timezone
from web.models import SiteSettings, Route, Article
class Command(BaseCommand):
    help = '初始化已确认的业务区域与基础知识；不会覆盖管理员修改'
    def handle(self,*args,**kwargs):
        SiteSettings.objects.get_or_create(pk=1)
        routes=[('central-asia','asia','中国—中亚','中亚地区各国'),('europe-uk','europe','中国—欧洲及英国','欧洲各国及英国'),('russia-belarus','russia','中国—俄罗斯与白俄罗斯','俄罗斯、白俄罗斯'),('southeast-asia','southeast','中国—东南亚','东南亚各国')]
        for i,(slug,region,title,countries) in enumerate(routes):
            Route.objects.get_or_create(slug=slug,defaults=dict(title=title,region=region,countries=countries,summary='面向'+countries+'的货物整车运输需求，按具体起讫地沟通服务方案。',body='服务范围\n'+countries+'。请提供具体城市、装卸地址及货物信息，确认可承运线路。\n\n承运方案\n根据货物类型、重量体积、包装、出货时间与装卸要求，沟通车型、衔接方式及所需资料。部分目的地可能涉及不同运输衔接方式，具体以确认的方案为准。\n\n费用与时效\n费用、时效和通关要求受实际线路、运输安排与口岸情况影响，请以业务确认结果为准。',published=True,order=i))
        entries=[
        ('ftl-inquiry-checklist','整车运输询价，需要准备哪些信息？','询价准备','整理起讫地、货物和时间要求，让运输需求更清晰。','先明确起讫地\n提供装货地与卸货地的国家、城市和详细地址，说明装卸时间窗口及现场限制。\n\n描述货物\n准备货物品名、包装、件数、总毛重、总体积和单件尺寸。说明是否涉及危险品、温控或其他特殊要求，不能只提供笼统的货类名称。\n\n说明时间与服务边界\n提供计划出货时间、期望到货时间，以及需要协助的运输和单证环节。确认报价包含的项目、有效期、额外费用条件与双方责任。'),
        ('truck-selection','如何沟通整车运输的车型需求？','运输知识','车型需要结合尺寸、重量、装卸条件与实际线路确认。','先整理货物参数\n货物总重、总体积并不足以决定车型，还需要单件尺寸、可否堆叠、重心位置及包装方式。\n\n明确装卸条件\n说明侧装、顶装、尾装或叉车装卸需求，以及现场限高、道路与设备条件。\n\n按线路确认适用车型\n不同国家、路段和口岸的车辆要求可能不同，车型、载重与尺寸应结合实际运输方案核实，不宜把某一种车辆的参数用于所有线路。'),
        ('transport-process','国际公路整车运输，一般如何衔接？','操作流程','从需求确认、资料准备到交付，梳理常见沟通节点。','需求确认\n核实货物、地址、时间与服务范围，明确费用组成和责任边界。\n\n资料与装车\n按相关方确认的清单准备单证，检查货物包装、标识及装载条件，记录装车信息。\n\n运输与跨境环节\n按约定沟通运输节点，配合相关机构要求。不同线路可能涉及换装或其他运输衔接。\n\n交付与归档\n核对签收与异常情况，保存约定的交付凭证和沟通记录。实际流程以具体线路及合同约定为准。'),
        ('shipping-documents','跨境运输单证，应该如何准备？','单证资料','以一致、完整、适用为原则，提前核对资料要求。','建立适用的资料清单\n常见沟通资料涉及货物清单、商业发票、装箱信息及相关业务文件。最终所需单证应由报关及业务相关方结合货物与目的地要求确认。\n\n保持信息一致\n核对货物名称、数量、重量、包装、收发货方与地址，避免不同文件之间出现矛盾。\n\n特殊货物另行核实\n涉及许可证、检验检疫、危险品或其他特殊监管要求时，需要在承运前向相应机构核实。本文不构成任何国家的完整通关清单。'),
        ('transit-time-factors','哪些因素会影响跨境运输时效？','常见问题','理解时效的适用条件，便于安排合理的出货计划。','先确认时效口径\n明确时效从哪个节点开始、在哪个节点结束，是否包含等候、通关与末端交付。\n\n关注实际影响因素\n装车准备、单证完整性、道路与天气、口岸处理、节假日及运输衔接都可能影响进度。\n\n保留计划空间\n对于有明确交付期限的货物，应提前说明时间要求，并沟通节点反馈与异常处理方式。参考时效与保证到达日期应明确区分。'),
        ('exception-handling','货物运输出现异常，如何整理沟通信息？','操作流程','记录事实、保存凭证、及时沟通，方便各方核实处理。','先记录事实\n整理发生时间、位置、涉及货物、已知情况与联系人，区分已确认信息和待核实信息。\n\n保存原始凭证\n在确保人员安全的前提下，保存照片、签收记录、包装情况与沟通记录，不擅自改变证据状态。\n\n按约定推进处理\n及时通知相关责任方，确认后续动作、处理进度与反馈时间。索赔及责任认定以合同、保险条款和适用规定为准。')]
        for slug,title,category,summary,body in entries:
            Article.objects.get_or_create(slug=slug,defaults=dict(title=title,category=category,summary=summary,body=body,kind='resources',published=True,published_at=timezone.now()))
        self.stdout.write(self.style.SUCCESS('内容初始化完成（保留已有内容）'))
