export type TaskStatus = 'PENDING' | 'READY' | 'RUNNING' | 'REVIEWING' | 'SUCCEEDED' | 'FAILED';

export interface Task {
  task_id: string;
  depends_on: string[];
  status: TaskStatus;
  assignee: string;
  attempt_count: number;
  error?: string | null;
}