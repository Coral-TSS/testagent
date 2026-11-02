import { useQuery } from "@tanstack/react-query";
import { Button, Form, Select } from "antd";
import { useEffect } from "react";

import { api } from "../api/client";
import type { Person, RequirementPerson, Role } from "../api/types";

export const ROLES: [Role, string][] = [
  ["owner", "Owner"],
  ["developer", "Developer"],
  ["tester", "Tester"],
];

/** Picks owner/developer/tester people for a requirement (BR: confirm requires an owner). */
export function PeopleRolePicker({
  value,
  disabled,
  saving,
  onSave,
}: {
  value: RequirementPerson[];
  disabled?: boolean;
  saving?: boolean;
  onSave: (people: { person_id: string; role: Role }[]) => void;
}) {
  const persons = useQuery({ queryKey: ["persons", false], queryFn: () => api<Person[]>("/persons") });
  const [form] = Form.useForm();
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
      onFinish={(v: Record<Role, string[] | undefined>) =>
        onSave(ROLES.flatMap(([role]) => (v[role] || []).map((person_id) => ({ person_id, role }))))
      }
    >
      {ROLES.map(([role, label]) => (
        <Form.Item key={role} name={role} label={label} style={{ marginBottom: 8 }}>
          <Select mode="multiple" options={options} optionFilterProp="label" placeholder={`Choose ${label}`} />
        </Form.Item>
      ))}
      <Button size="small" htmlType="submit" loading={saving}>
        Save people
      </Button>
    </Form>
  );
}
