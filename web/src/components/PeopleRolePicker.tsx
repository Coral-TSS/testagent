import { useQuery } from "@tanstack/react-query";
import { Button, Form, Select, type FormInstance } from "antd";
import { useEffect } from "react";

import { api } from "../api/client";
import type { Person, RequirementPerson, Role } from "../api/types";

export const ROLES: [Role, string][] = [
  ["owner", "负责人"],
  ["developer", "开发"],
  ["tester", "测试"],
];

/** Picks owner/developer/tester people for a requirement (BR: confirm requires an owner). */
export function peoplePayload(values: Partial<Record<Role, string[]>>): { person_id: string; role: Role }[] {
  return ROLES.flatMap(([role]) => (values[role] || []).map((person_id) => ({ person_id, role })));
}

export function PeopleRolePicker({
  value,
  disabled,
  saving,
  onSave,
  form: external,
  showSave = true,
}: {
  value: RequirementPerson[];
  disabled?: boolean;
  saving?: boolean;
  onSave: (people: { person_id: string; role: Role }[]) => void;
  form?: FormInstance;
  showSave?: boolean;
}) {
  const persons = useQuery({ queryKey: ["persons", false], queryFn: () => api<Person[]>("/persons") });
  const [own] = Form.useForm();
  const form = external || own;
  useEffect(() => {
    form.setFieldsValue(Object.fromEntries(ROLES.map(([role]) => [role, value.filter((p) => p.role === role).map((p) => p.person_id)])));
  }, [value, form]);
  const options = (persons.data || []).map((p) => ({ value: p.id, label: p.name, disabled: !p.active }));
  return (
    <Form
      form={form}
      layout="horizontal"
      labelCol={{ span: 4 }}
      disabled={disabled}
      onFinish={(v: Partial<Record<Role, string[]>>) => onSave(peoplePayload(v))}
    >
      {ROLES.map(([role, label]) => (
        <Form.Item key={role} name={role} label={label} style={{ marginBottom: 8 }}>
          <Select mode="multiple" options={options} optionFilterProp="label" placeholder={`选择${label}`} />
        </Form.Item>
      ))}
      {showSave && (
        <Button size="small" htmlType="submit" loading={saving}>
          保存人员
        </Button>
      )}
    </Form>
  );
}
