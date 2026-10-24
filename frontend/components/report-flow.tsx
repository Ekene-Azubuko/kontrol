"use client";
import { useState } from "react";
import { z } from "zod";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  FileImage,
  MapPin,
} from "lucide-react";
import { useData } from "@/lib/api";
import type { Report } from "@/lib/types";
import { Badge, ErrorBox, Panel, useAction } from "./shared";
import { PageHeading } from "./page-heading";
import { Button } from "./ui/button";
import { IncidentMap } from "./map";
import { time } from "@/lib/utils";
const schema = z.object({
  category: z.enum([
    "collision",
    "fire",
    "rescue",
    "road",
    "wildfire",
    "smoke",
    "medical",
    "power",
    "water",
  ]),
  description: z.string().min(10).max(4000),
  location: z.string().min(2).max(160),
  latitude: z.number().min(-90).max(90),
  longitude: z.number().min(-180).max(180),
  observed_at: z.string(),
  photo: z.string().nullable(),
  reported_casualties: z.number().int().min(0).max(100).nullable(),
});
/** Guide residents through validation and confirm durable submission before analysis completes. */
export function ReportFlow() {
  const reports = useData<Report[]>("/reports");
  const [step, setStep] = useState(1);
  const [category, setCategory] =
    useState<z.infer<typeof schema>["category"]>("collision");
  const [casualties, setCasualties] = useState("");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [latitude, setLatitude] = useState(37.7749);
  const [longitude, setLongitude] = useState(-122.4194);
  const [observed, setObserved] = useState("");
  const [photo, setPhoto] = useState<string | null>(null);
  const [validation, setValidation] = useState("");
  const [submitted, setSubmitted] = useState<Report | null>(null);
  const action = useAction();
  async function attach(file?: File) {
    if (!file) return;
    if (
      !["image/jpeg", "image/png", "image/webp"].includes(file.type) ||
      file.size > 1000000
    ) {
      setValidation("Choose a JPEG, PNG or WebP photo under 1 MB.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setPhoto(String(reader.result));
      setValidation("");
    };
    reader.readAsDataURL(file);
  }
  async function submit() {
    const value = schema.safeParse({
      category,
      description,
      location,
      latitude,
      longitude,
      observed_at: observed
        ? new Date(observed).toISOString()
        : new Date().toISOString(),
      photo,
      reported_casualties: casualties === "" ? null : Number(casualties),
    });
    if (!value.success) {
      setValidation(value.error.issues[0].message);
      return;
    }
    const result = await action.act<Report>("/reports", value.data, "POST", "");
    if (result) setSubmitted(result);
  }
  return (
    <>
      <PageHeading
        eyebrow="RESIDENT OBSERVATIONS"
        title="Share what you see"
        subtitle="Report an incident. Kontrol Agents assess it immediately while you track its status here."
      />
      <div className="report-layout">
        <Panel
          title={submitted ? "Report received" : "Submit an incident report"}
        >
          {submitted ? (
            <div className="confirmation">
              <CheckCircle2 size={48} />
              <h2>Your observation is in the queue.</h2>
              <p>
                You do not need to wait for analysis. A coordinator can review
                your original report now.
              </p>
              <span className="reference">
                REF {submitted.id.slice(0, 8).toUpperCase()}
              </span>
              <Badge
                value={
                  reports.data?.find((item) => item.id === submitted.id)
                    ?.status || submitted.status
                }
              />
              <Button
                variant="secondary"
                onClick={() => {
                  setSubmitted(null);
                  setStep(1);
                  setDescription("");
                  setPhoto(null);
                  setCasualties("");
                }}
              >
                Submit another observation
              </Button>
            </div>
          ) : (
            <>
              <div className="steps">
                {["Observation", "Location", "Review"].map((label, index) => (
                  <div
                    key={label}
                    className={step >= index + 1 ? "active" : ""}
                  >
                    <span>
                      {step > index + 1 ? <Check size={15} /> : index + 1}
                    </span>
                    {label}
                  </div>
                ))}
              </div>
              <div className="form">
                {step === 1 && (
                  <>
                    <fieldset className="category-fieldset">
                      <legend>What are you reporting?</legend>
                      <div className="category-grid">
                        {[
                          "collision",
                          "fire",
                          "rescue",
                          "road",
                          "wildfire",
                          "smoke",
                          "medical",
                          "power",
                          "water",
                        ].map((value) => (
                          <button
                            key={value}
                            type="button"
                            aria-pressed={category === value}
                            className={category === value ? "selected" : ""}
                            onClick={() =>
                              setCategory(value as typeof category)
                            }
                          >
                            {value === "road" ? "Road obstruction" : value}
                          </button>
                        ))}
                      </div>
                    </fieldset>
                    <label>
                      Describe your observation
                      <textarea
                        rows={5}
                        minLength={10}
                        maxLength={4000}
                        value={description}
                        onChange={(event) => setDescription(event.target.value)}
                        placeholder="Describe what you observed and where. Avoid personal or sensitive information."
                      />
                      <small>
                        {description.length} / 4000 characters · At least 10
                      </small>
                    </label>
                    <label>
                      Reported injured people (if known)
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={1}
                        value={casualties}
                        onChange={(event) => setCasualties(event.target.value)}
                        placeholder="Unknown"
                      />
                      <small>
                        Leave blank if unknown. Describe observations only; no
                        diagnosis is needed.
                      </small>
                    </label>
                    <label>
                      Observation time (optional)
                      <input
                        type="datetime-local"
                        value={observed}
                        onChange={(event) => setObserved(event.target.value)}
                      />
                    </label>
                    <label className="photo-upload">
                      <FileImage size={22} />
                      <span>
                        {photo ? "Photo attached ✓" : "Add an optional photo"}
                        <small>JPEG, PNG, WebP · up to 1 MB</small>
                      </span>
                      <input
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        onChange={(event) => attach(event.target.files?.[0])}
                      />
                    </label>
                  </>
                )}
                {step === 2 && (
                  <>
                    <label>
                      Incident location
                      <input
                        value={location}
                        onChange={(event) => {
                          setLocation(event.target.value);
                        }}
                        placeholder="Street address, intersection, or landmark"
                      />
                    </label>
                    <p className="muted">
                      <MapPin size={14} /> Enter the location and click the map
                      to place the incident pin precisely.
                    </p>
                    <IncidentMap
                      items={[]}
                      compact
                      pin={[latitude, longitude]}
                      onPin={(lat, lon) => {
                        setLatitude(lat);
                        setLongitude(lon);
                      }}
                    />
                    <div className="two-columns">
                      <label>
                        Latitude
                        <input
                          type="number"
                          step="any"
                          value={latitude}
                          onChange={(event) =>
                            setLatitude(Number(event.target.value))
                          }
                        />
                      </label>
                      <label>
                        Longitude
                        <input
                          type="number"
                          step="any"
                          value={longitude}
                          onChange={(event) =>
                            setLongitude(Number(event.target.value))
                          }
                        />
                      </label>
                    </div>
                  </>
                )}
                {step === 3 && (
                  <div className="report-review">
                    <Badge value={category} />
                    <h2>{location}</h2>
                    <p>{description}</p>
                    <dl>
                      <dt>Coordinates</dt>
                      <dd>
                        {latitude.toFixed(5)}, {longitude.toFixed(5)}
                      </dd>
                      <dt>Observed</dt>
                      <dd>
                        {observed
                          ? new Date(observed).toLocaleString()
                          : "At submission time"}
                      </dd>
                      <dt>Reported injured</dt>
                      <dd>{casualties === "" ? "Unknown" : casualties}</dd>
                      <dt>Photo</dt>
                      <dd>{photo ? "Attached" : "No attachment"}</dd>
                    </dl>
                    <div className="callout">
                      This report is private to the response team. Kontrol
                      Agents will propose a response; a coordinator must approve
                      all assignments.
                    </div>
                  </div>
                )}
                {validation && <ErrorBox message={validation} />}
                {action.feedback}
                <div className="row">
                  <Button
                    variant="ghost"
                    disabled={step === 1 || action.busy}
                    onClick={() => setStep(step - 1)}
                  >
                    <ArrowLeft size={16} />
                    Back
                  </Button>
                  {step < 3 ? (
                    <Button
                      disabled={
                        (step === 1 && description.length < 10) ||
                        (step === 2 && location.length < 2)
                      }
                      onClick={() => setStep(step + 1)}
                    >
                      Continue
                      <ArrowRight size={16} />
                    </Button>
                  ) : (
                    <Button disabled={action.busy} onClick={submit}>
                      {action.busy ? "Submitting…" : "Submit report"}
                    </Button>
                  )}
                </div>
              </div>
            </>
          )}
        </Panel>
        <Panel title="Your reports" eyebrow="PRIVATE TO YOU & COORDINATORS">
          <div className="my-reports">
            {reports.data?.slice(0, 12).map((report) => (
              <article key={report.id}>
                <div className="row">
                  <strong>
                    {report.category} · {report.location}
                  </strong>
                  <small>{time(report.created_at)}</small>
                </div>
                <p>{report.description}</p>
                <div className="row">
                  <small className="mono">
                    REF {report.id.slice(0, 8).toUpperCase()}
                  </small>
                  <Badge value={report.status} />
                </div>
              </article>
            ))}
            {!reports.data?.length && (
              <p className="muted">
                Your submitted observations will appear here with their
                processing status.
              </p>
            )}
          </div>
        </Panel>
      </div>
    </>
  );
}
