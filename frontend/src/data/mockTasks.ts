import type { Task } from '../types/task';

export const mockTasks: Task[] = [
  { task_id: 'T01', depends_on: [], status: 'SUCCEEDED', assignee: 'Orchestrator', attempt_count: 1 },
  { task_id: 'T02', depends_on: ['T01'], status: 'SUCCEEDED', assignee: 'DB-01', attempt_count: 1 },
  { task_id: 'T03', depends_on: ['T02'], status: 'RUNNING', assignee: 'BE-01', attempt_count: 1 },
  { task_id: 'T04', depends_on: ['T03'], status: 'PENDING', assignee: 'BE-01', attempt_count: 0 },
  { task_id: 'T06', depends_on: ['T01'], status: 'RUNNING', assignee: 'FE-01', attempt_count: 1 },
];