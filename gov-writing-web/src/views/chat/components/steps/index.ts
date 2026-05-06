import CommonStep from './CommonStep.vue';
import DocumentStep from './DocumentStep.vue';
import PlainTextStep from './PlainTextStep.vue';
import PlanTextStep from './PlanTextStep.vue';
import ReportCardStep from './ReportCardStep.vue';
import ResultStep from './ResultStep.vue';
import SearchResultStep from './SearchResultStep.vue';
import TableCardStep from './TableCardStep.vue';
import TemplateStep from './TemplateStep.vue';
import ToolStep from './ToolStep.vue';

// 步骤组件映射
export const stepComponents: Record<string, any> = {
  common: CommonStep,
  planText: PlanTextStep,
  tool: ToolStep,
  template: TemplateStep,
  document: DocumentStep,
  reportCard: ReportCardStep,
  tableCard: TableCardStep,
  searchResult: SearchResultStep,
  text: PlainTextStep,
  result: ResultStep,
};

export default stepComponents;
