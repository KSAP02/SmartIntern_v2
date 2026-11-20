// "Add title to my roles": a job title you'd also want becomes a role in Search criteria.
import { useEffect, useState } from "react";
import { api, errorMessage } from "../../lib/api";
import { Button, Input } from "../ui";
import { Modal } from "../Modal";
import { useToast } from "../Toast";

/** Suggest a clean role from a job title: drop gender tags, ids and trailing locations / notes. */
export function roleFromTitle(title: string): string {
  return title
    .replace(/\((?:m|w|f|d|x|h|all|mwd|wmd)(?:\s*[/|,]\s*(?:m|w|f|d|x|h))*\)/gi, "")
    .replace(/\(\s*[A-Z]?\d{3,}\s*\)/g, "")
    .replace(/\s+[-–—|]\s+.*$/, "")
    .replace(/\s*\(.*?\)\s*$/, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export function AddRoleModal({ title, open, onClose, onAdded }: { title: string; open: boolean; onClose: () => void; onAdded?: (role: string) => void }) {
  const toast = useToast();
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) setRole(roleFromTitle(title));
  }, [open, title]);

  const add = async () => {
    const r = role.trim();
    if (r.length < 2) return;
    setBusy(true);
    try {
      await api.addRole(r);
      toast.success(`“${r}” added to your roles`, "Jobs already gathered are re-checked; the search plan now includes it.");
      onAdded?.(r);
      onClose();
    } catch (e) {
      toast.error("Couldn't add the role", errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add title to my roles"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={role.trim().length < 2} onClick={() => void add()}>
            Add role
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void add();
        }}
        className="space-y-3"
      >
        <label htmlFor="add-role" className="block text-xs text-zinc-500">
          Role (edit it to the wording you'd search for)
        </label>
        <Input id="add-role" value={role} onChange={(e) => setRole(e.target.value)} autoFocus />
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Jobs with this kind of title will count as relevant, and your search plan gets one more search per place (it is searched when the request budget allows). You can remove it any time in Search Settings → Roles you want.
        </p>
      </form>
    </Modal>
  );
}
