from django.db import migrations

# The database itself refuses to change or remove an audit entry, so raw SQL and bulk queries cannot either. The one change it allows is the patient link
# being cleared when a patient row is deleted (on_delete SET_NULL).
CREATE = """
CREATE FUNCTION audit_log_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND (to_jsonb(NEW) - 'patient_id') = (to_jsonb(OLD) - 'patient_id') AND NEW.patient_id IS NULL THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit_log entries are never edited or deleted';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
"""
DROP = "DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log; DROP FUNCTION IF EXISTS audit_log_append_only();"


class Migration(migrations.Migration):

    dependencies = [
        ('hospital_setup', '0003_model_integrity'),
    ]

    operations = [migrations.RunSQL(CREATE, DROP)]
